import datetime
import json
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers.base import JobLookupError
from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.message_components import At, Plain
from .utils import is_outdated, save_reminder_data, HolidayManager
from .reminder_handlers import ReminderMessageHandler, TaskExecutor, ReminderExecutor, SimpleMessageSender

# 使用全局注册表来保存调度器实例
# 现在即使在模块重载后，调度器实例也能保持，我看你还怎么创建新实例（恼）
import sys
if not hasattr(sys, "_GLOBAL_SCHEDULER_REGISTRY"):
    sys._GLOBAL_SCHEDULER_REGISTRY = {
        'scheduler': None
    }
    logger.info("创建全局调度器注册表")
else:
    logger.info("使用现有全局调度器注册表")

class ReminderScheduler:
    def __new__(cls, context, reminder_data, data_file, unique_session=False):
        # 使用实例属性存储初始化状态
        instance = super(ReminderScheduler, cls).__new__(cls)
        instance._first_init = True  # 首次初始化
        
        logger.info("创建 ReminderScheduler 实例")
        return instance
    
    def __init__(self, context, reminder_data, data_file, unique_session=False):
        self.context = context
        self.reminder_data = reminder_data
        self.data_file = data_file
        self.unique_session = unique_session
        
        # 定义微信相关平台列表，用于特殊处理
        self.wechat_platforms = ["gewechat", "wechatpadpro", "wecom"]
        
        # 从全局注册表获取调度器，如果不存在则创建
        if sys._GLOBAL_SCHEDULER_REGISTRY['scheduler'] is None:
            sys._GLOBAL_SCHEDULER_REGISTRY['scheduler'] = AsyncIOScheduler()
            logger.info("创建新的全局 AsyncIOScheduler 实例")
        else:
            logger.info("使用现有全局 AsyncIOScheduler 实例")
        
        # 使用全局注册表中的调度器
        self.scheduler = sys._GLOBAL_SCHEDULER_REGISTRY['scheduler']
        
        # 创建节假日管理器
        self.holiday_manager = HolidayManager()
        
        # 如果有现有任务且是重新初始化，清理所有现有任务
        if not getattr(self, '_first_init', True) and self.scheduler.get_jobs():
            logger.info("检测到重新初始化，清理现有任务")
            for job in self.scheduler.get_jobs():
                if job.id.startswith("reminder_"):
                    try:
                        self.scheduler.remove_job(job.id)
                    except JobLookupError:
                        pass
        
        # 初始化任务
        self._init_scheduler()
        
        # 确保调度器运行
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("启动全局 AsyncIOScheduler")
        
        # 重置首次初始化标志
        self._first_init = False
    
    def _init_scheduler(self):
        '''初始化定时器'''
        logger.info(f"开始初始化调度器，加载 {sum(len(reminders) for reminders in self.reminder_data.values())} 个提醒/任务")
        
        # 清理当前实例关联的所有任务
        for job in self.scheduler.get_jobs():
            if job.id.startswith("reminder_"):
                try:
                    self.scheduler.remove_job(job.id)
                    logger.info(f"移除现有任务: {job.id}")
                except JobLookupError:
                    pass
        
        # 重新添加所有任务
        for group in self.reminder_data:
            for i, reminder in enumerate(self.reminder_data[group]):
                if "datetime" not in reminder:
                    continue
                
                # 处理不完整的时间格式问题
                datetime_str = reminder["datetime"]
                try:
                    if ":" in datetime_str and len(datetime_str.split(":")) == 2 and "-" not in datetime_str:
                        # 处理只有时分格式的时间（如"14:50"）
                        today = datetime.datetime.now()
                        hour, minute = map(int, datetime_str.split(":"))
                        dt = today.replace(hour=hour, minute=minute)
                        if dt < today:  # 如果时间已过，设置为明天
                            dt += datetime.timedelta(days=1)
                        # 更新reminder中的datetime为完整格式
                        reminder["datetime"] = dt.strftime("%Y-%m-%d %H:%M")
                        self.reminder_data[group][i] = reminder
                    dt = datetime.datetime.strptime(reminder["datetime"], "%Y-%m-%d %H:%M")
                except ValueError as e:
                    logger.error(f"无法解析时间格式 '{reminder['datetime']}': {str(e)}，跳过此提醒")
                    continue
                
                # 判断过期
                repeat_type = reminder.get("repeat", "none")
                if (repeat_type == "none" or 
                    not any(repeat_key in repeat_type for repeat_key in ["daily", "weekly", "monthly", "yearly"])) and is_outdated(reminder):
                    logger.info(f"跳过已过期的提醒: {reminder['text']}")
                    continue
                
                # 生成唯一的任务ID，添加时间戳确保唯一性
                timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                job_id = f"reminder_{group}_{i}_{timestamp}"
                
                # 根据重复类型设置不同的触发器
                if reminder.get("repeat") == "daily":
                    self.scheduler.add_job(
                        self._reminder_callback,
                        'cron',
                        args=[group, reminder],
                        hour=dt.hour,
                        minute=dt.minute,
                        misfire_grace_time=60,
                        id=job_id
                    )
                    logger.info(f"添加每日提醒: {reminder['text']} 时间: {dt.hour}:{dt.minute} ID: {job_id}")
                elif reminder.get("repeat") == "daily_workday":
                    # 每个工作日重复
                    self.scheduler.add_job(
                        self._check_and_execute_workday,
                        'cron',
                        args=[group, reminder],
                        hour=dt.hour,
                        minute=dt.minute,
                        misfire_grace_time=60,
                        id=job_id
                    )
                    logger.info(f"添加工作日提醒: {reminder['text']} 时间: {dt.hour}:{dt.minute} ID: {job_id}")
                elif reminder.get("repeat") == "daily_holiday":
                    # 每个法定节假日重复
                    self.scheduler.add_job(
                        self._check_and_execute_holiday,
                        'cron',
                        args=[group, reminder],
                        hour=dt.hour,
                        minute=dt.minute,
                        misfire_grace_time=60,
                        id=job_id
                    )
                    logger.info(f"添加节假日提醒: {reminder['text']} 时间: {dt.hour}:{dt.minute} ID: {job_id}")
                elif reminder.get("repeat") == "weekly":
                    self.scheduler.add_job(
                        self._reminder_callback,
                        'cron',
                        args=[group, reminder],
                        day_of_week=dt.weekday(),
                        hour=dt.hour,
                        minute=dt.minute,
                        misfire_grace_time=60,
                        id=job_id
                    )
                    logger.info(f"添加每周提醒: {reminder['text']} 时间: 每周{dt.weekday()+1} {dt.hour}:{dt.minute} ID: {job_id}")
                elif reminder.get("repeat") == "weekly_workday":
                    # 每周的这一天，但仅工作日执行
                    self.scheduler.add_job(
                        self._check_and_execute_workday,
                        'cron',
                        args=[group, reminder],
                        day_of_week=dt.weekday(),  # 保留这个限制，因为"每周"需要指定星期几
                        hour=dt.hour,
                        minute=dt.minute,
                        misfire_grace_time=60,
                        id=job_id
                    )
                    logger.info(f"添加每周工作日提醒: {reminder['text']} 时间: 每周{dt.weekday()+1} {dt.hour}:{dt.minute} ID: {job_id}")
                elif reminder.get("repeat") == "weekly_holiday":
                    # 每周的这一天，但仅法定节假日执行
                    self.scheduler.add_job(
                        self._check_and_execute_holiday,
                        'cron',
                        args=[group, reminder],
                        day_of_week=dt.weekday(),
                        hour=dt.hour,
                        minute=dt.minute,
                        misfire_grace_time=60,
                        id=job_id
                    )
                    logger.info(f"添加每周节假日提醒: {reminder['text']} 时间: 每周{dt.weekday()+1} {dt.hour}:{dt.minute} ID: {job_id}")
                elif reminder.get("repeat") == "monthly":
                    self.scheduler.add_job(
                        self._reminder_callback,
                        'cron',
                        args=[group, reminder],
                        day=dt.day,
                        hour=dt.hour,
                        minute=dt.minute,
                        misfire_grace_time=60,
                        id=job_id
                    )
                    logger.info(f"添加每月提醒: {reminder['text']} 时间: 每月{dt.day}日 {dt.hour}:{dt.minute} ID: {job_id}")
                elif reminder.get("repeat") == "monthly_workday":
                    # 每月的这一天，但仅工作日执行
                    self.scheduler.add_job(
                        self._check_and_execute_workday,
                        'cron',
                        args=[group, reminder],
                        day=dt.day,  # 保留这个限制，因为"每月"需要指定几号
                        hour=dt.hour,
                        minute=dt.minute,
                        misfire_grace_time=60,
                        id=job_id
                    )
                    logger.info(f"添加每月工作日提醒: {reminder['text']} 时间: 每月{dt.day}日 {dt.hour}:{dt.minute} ID: {job_id}")
                elif reminder.get("repeat") == "monthly_holiday":
                    # 每月的这一天，但仅法定节假日执行
                    self.scheduler.add_job(
                        self._check_and_execute_holiday,
                        'cron',
                        args=[group, reminder],
                        day=dt.day,
                        hour=dt.hour,
                        minute=dt.minute,
                        misfire_grace_time=60,
                        id=job_id
                    )
                    logger.info(f"添加每月节假日提醒: {reminder['text']} 时间: 每月{dt.day}日 {dt.hour}:{dt.minute} ID: {job_id}")
                elif reminder.get("repeat") == "yearly":
                    self.scheduler.add_job(
                        self._reminder_callback,
                        'cron',
                        args=[group, reminder],
                        month=dt.month,
                        day=dt.day,
                        hour=dt.hour,
                        minute=dt.minute,
                        misfire_grace_time=60,
                        id=job_id
                    )
                    logger.info(f"添加每年提醒: {reminder['text']} 时间: 每年{dt.month}月{dt.day}日 {dt.hour}:{dt.minute} ID: {job_id}")
                elif reminder.get("repeat") == "yearly_workday":
                    # 每年的这一天，但仅工作日执行
                    self.scheduler.add_job(
                        self._check_and_execute_workday,
                        'cron',
                        args=[group, reminder],
                        month=dt.month,  # 保留这个限制，因为"每年"需要指定月份
                        day=dt.day,      # 保留这个限制，因为"每年"需要指定日期
                        hour=dt.hour,
                        minute=dt.minute,
                        misfire_grace_time=60,
                        id=job_id
                    )
                    logger.info(f"添加每年工作日提醒: {reminder['text']} 时间: 每年{dt.month}月{dt.day}日 {dt.hour}:{dt.minute} ID: {job_id}")
                elif reminder.get("repeat") == "yearly_holiday":
                    # 每年的这一天，但仅法定节假日执行
                    self.scheduler.add_job(
                        self._check_and_execute_holiday,
                        'cron',
                        args=[group, reminder],
                        month=dt.month,
                        day=dt.day,
                        hour=dt.hour,
                        minute=dt.minute,
                        misfire_grace_time=60,
                        id=job_id
                    )
                    logger.info(f"添加每年节假日提醒: {reminder['text']} 时间: 每年{dt.month}月{dt.day}日 {dt.hour}:{dt.minute} ID: {job_id}")
                else:
                    self.scheduler.add_job(
                        self._reminder_callback,
                        'date',
                        args=[group, reminder],
                        run_date=dt,
                        misfire_grace_time=60,
                        id=job_id
                    )
                    logger.info(f"添加一次性提醒: {reminder['text']} 时间: {dt.strftime('%Y-%m-%d %H:%M')} ID: {job_id}")
    
    async def _check_and_execute_workday(self, unified_msg_origin: str, reminder: dict):
        '''检查当天是否为工作日，如果是则执行提醒'''
        today = datetime.datetime.now()
        logger.info(f"检查日期 {today.strftime('%Y-%m-%d')} 是否为工作日，提醒内容: {reminder['text']}")
        
        is_workday = await self.holiday_manager.is_workday(today)
        logger.info(f"日期 {today.strftime('%Y-%m-%d')} 工作日检查结果: {is_workday}")
        
        if is_workday:
            # 如果是工作日则执行提醒
            logger.info(f"确认今天是工作日，执行提醒: {reminder['text']}")
            await self._reminder_callback(unified_msg_origin, reminder)
        else:
            logger.info(f"今天不是工作日，跳过执行提醒: {reminder['text']}")
    
    async def _check_and_execute_holiday(self, unified_msg_origin: str, reminder: dict):
        '''检查当天是否为法定节假日，如果是则执行提醒'''
        today = datetime.datetime.now()
        logger.info(f"检查日期 {today.strftime('%Y-%m-%d')} 是否为法定节假日，提醒内容: {reminder['text']}")
        
        is_holiday = await self.holiday_manager.is_holiday(today)
        logger.info(f"日期 {today.strftime('%Y-%m-%d')} 法定节假日检查结果: {is_holiday}")
        
        if is_holiday:
            # 如果是法定节假日则执行提醒
            logger.info(f"确认今天是法定节假日，执行提醒: {reminder['text']}")
            await self._reminder_callback(unified_msg_origin, reminder)
        else:
            logger.info(f"今天不是法定节假日，跳过执行提醒: {reminder['text']}")
    
    async def _reminder_callback(self, unified_msg_origin: str, reminder: dict):
        '''提醒回调函数'''
        provider = self.context.get_using_provider()
        
        # 区分提醒和任务
        is_task = reminder.get("is_task", False)
        
        logger.info(f"开始执行{'任务' if is_task else '提醒'}: {reminder['text']} 在 {unified_msg_origin}")
        
        # 初始化处理器
        task_executor = TaskExecutor(self.context, self.wechat_platforms)
        reminder_executor = ReminderExecutor(self.context, self.wechat_platforms)
        simple_sender = SimpleMessageSender(self.context, self.wechat_platforms)
        
        if provider:
            logger.info(f"使用提供商: {provider.meta().type}")
            if is_task:
                # 任务模式：模拟用户发送消息，让AI执行任务
                func_tool = self.context.get_llm_tool_manager()
                logger.info(f"LLM工具管理器加载成功: {func_tool is not None}")
                await task_executor.execute_task(unified_msg_origin, reminder, provider, func_tool)
            else:
                # 提醒模式：只是提醒用户
                await reminder_executor.execute_reminder(unified_msg_origin, reminder, provider)
        else:
            logger.warning(f"没有可用的提供商，使用简单消息")
            await simple_sender.send_simple_message(unified_msg_origin, reminder, is_task)
        
        # 如果是一次性任务（非重复任务），执行后从数据中删除
        if reminder.get("repeat", "none") == "none":
            if unified_msg_origin in self.reminder_data:
                # 查找并删除这个提醒
                for i, r in enumerate(self.reminder_data[unified_msg_origin]):
                    if r == reminder:  # 比较整个字典
                        self.reminder_data[unified_msg_origin].pop(i)
                        logger.info(f"One-time {'task' if is_task else 'reminder'} removed: {reminder['text']}")
                        await save_reminder_data(self.data_file, self.reminder_data)
                        break
    
    def add_job(self, msg_origin, reminder, dt):
        '''添加定时任务'''
        # 生成唯一的任务ID
        job_id = f"reminder_{msg_origin}_{len(self.reminder_data[msg_origin])-1}"
        
        # 根据重复类型设置不同的触发器
        if reminder.get("repeat") == "daily":
            self.scheduler.add_job(
                self._reminder_callback,
                'cron',
                args=[msg_origin, reminder],
                hour=dt.hour,
                minute=dt.minute,
                misfire_grace_time=60,
                id=job_id
            )
        elif reminder.get("repeat") == "daily_workday":
            # 每个工作日重复
            self.scheduler.add_job(
                self._check_and_execute_workday,
                'cron',
                args=[msg_origin, reminder],
                hour=dt.hour,
                minute=dt.minute,
                misfire_grace_time=60,
                id=job_id
            )
        elif reminder.get("repeat") == "daily_holiday":
            # 每个法定节假日重复
            self.scheduler.add_job(
                self._check_and_execute_holiday,
                'cron',
                args=[msg_origin, reminder],
                hour=dt.hour,
                minute=dt.minute,
                misfire_grace_time=60,
                id=job_id
            )
        elif reminder.get("repeat") == "weekly":
            self.scheduler.add_job(
                self._reminder_callback,
                'cron',
                args=[msg_origin, reminder],
                day_of_week=dt.weekday(),
                hour=dt.hour,
                minute=dt.minute,
                misfire_grace_time=60,
                id=job_id
            )
        elif reminder.get("repeat") == "weekly_workday":
            # 每周的这一天，但仅工作日执行
            self.scheduler.add_job(
                self._check_and_execute_workday,
                'cron',
                args=[msg_origin, reminder],
                day_of_week=dt.weekday(),  # 保留这个限制，因为"每周"需要指定星期几
                hour=dt.hour,
                minute=dt.minute,
                misfire_grace_time=60,
                id=job_id
            )
        elif reminder.get("repeat") == "weekly_holiday":
            # 每周的这一天，但仅法定节假日执行
            self.scheduler.add_job(
                self._check_and_execute_holiday,
                'cron',
                args=[msg_origin, reminder],
                day_of_week=dt.weekday(),
                hour=dt.hour,
                minute=dt.minute,
                misfire_grace_time=60,
                id=job_id
            )
        elif reminder.get("repeat") == "monthly":
            self.scheduler.add_job(
                self._reminder_callback,
                'cron',
                args=[msg_origin, reminder],
                day=dt.day,
                hour=dt.hour,
                minute=dt.minute,
                misfire_grace_time=60,
                id=job_id
            )
        elif reminder.get("repeat") == "monthly_workday":
            # 每月的这一天，但仅工作日执行
            self.scheduler.add_job(
                self._check_and_execute_workday,
                'cron',
                args=[msg_origin, reminder],
                day=dt.day,  # 保留这个限制，因为"每月"需要指定几号
                hour=dt.hour,
                minute=dt.minute,
                misfire_grace_time=60,
                id=job_id
            )
        elif reminder.get("repeat") == "monthly_holiday":
            # 每月的这一天，但仅法定节假日执行
            self.scheduler.add_job(
                self._check_and_execute_holiday,
                'cron',
                args=[msg_origin, reminder],
                day=dt.day,
                hour=dt.hour,
                minute=dt.minute,
                misfire_grace_time=60,
                id=job_id
            )
        elif reminder.get("repeat") == "yearly":
            self.scheduler.add_job(
                self._reminder_callback,
                'cron',
                args=[msg_origin, reminder],
                month=dt.month,
                day=dt.day,
                hour=dt.hour,
                minute=dt.minute,
                misfire_grace_time=60,
                id=job_id
            )
        elif reminder.get("repeat") == "yearly_workday":
            # 每年的这一天，但仅工作日执行
            self.scheduler.add_job(
                self._check_and_execute_workday,
                'cron',
                args=[msg_origin, reminder],
                month=dt.month,  # 保留这个限制，因为"每年"需要指定月份
                day=dt.day,      # 保留这个限制，因为"每年"需要指定日期
                hour=dt.hour,
                minute=dt.minute,
                misfire_grace_time=60,
                id=job_id
            )
        elif reminder.get("repeat") == "yearly_holiday":
            # 每年的这一天，但仅法定节假日执行
            self.scheduler.add_job(
                self._check_and_execute_holiday,
                'cron',
                args=[msg_origin, reminder],
                month=dt.month,
                day=dt.day,
                hour=dt.hour,
                minute=dt.minute,
                misfire_grace_time=60,
                id=job_id
            )
        else:
            self.scheduler.add_job(
                self._reminder_callback,
                'date',
                args=[msg_origin, reminder],
                run_date=dt,
                misfire_grace_time=60,
                id=job_id
            )
        return job_id
    
    def remove_job(self, job_id):
        '''删除定时任务'''
        try:
            self.scheduler.remove_job(job_id)
            logger.info(f"Successfully removed job: {job_id}")
            return True
        except JobLookupError:
            logger.error(f"Job not found: {job_id}")
            return False
    
    # 获取会话ID
    def get_session_id(self, unified_msg_origin, reminder):
        """
        根据会话隔离设置，获取正确的会话ID
        
        Args:
            unified_msg_origin: 原始会话ID
            reminder: 提醒/任务数据
            
        Returns:
            str: 处理后的会话ID
        """
        if not self.unique_session:
            return unified_msg_origin
            
        # 如果启用了会话隔离，并且有创建者ID，则在会话ID中添加用户标识
        creator_id = reminder.get("creator_id")
        if creator_id and ":" in unified_msg_origin:
            # 在群聊环境中添加用户ID
            if (":GroupMessage:" in unified_msg_origin or 
                "@chatroom" in unified_msg_origin or
                ":ChannelMessage:" in unified_msg_origin):
                # 分割会话ID并在末尾添加用户标识
                parts = unified_msg_origin.rsplit(":", 1)
                if len(parts) == 2:
                    return f"{parts[0]}:{parts[1]}_{creator_id}"
        
        return unified_msg_origin
    
    def get_original_session_id(self, session_id):
        """
        从隔离格式的会话ID中提取原始会话ID，用于消息发送
        """
        # 使用新的消息处理器来获取原始会话ID
        message_handler = ReminderMessageHandler(self.context, self.wechat_platforms)
        return message_handler.get_original_session_id(session_id)
    
    # 析构函数不执行操作
    def __del__(self):
        # 不关闭调度器，因为它是全局共享的
        pass

    @staticmethod
    def get_scheduler():
        """获取当前的全局调度器实例"""
        return sys._GLOBAL_SCHEDULER_REGISTRY.get('scheduler') 