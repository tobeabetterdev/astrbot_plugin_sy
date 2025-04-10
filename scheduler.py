import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers.base import JobLookupError
from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.message_components import At, Plain
from .utils import is_outdated, save_reminder_data, HolidayManager

class ReminderScheduler:
    def __init__(self, context, reminder_data, data_file):
        self.context = context
        self.reminder_data = reminder_data
        self.data_file = data_file
        self.scheduler = AsyncIOScheduler()
        self.holiday_manager = HolidayManager()  # 创建节假日管理器
        self._init_scheduler()
        self.scheduler.start()
    
    def _init_scheduler(self):
        '''初始化定时器'''
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
                
                if reminder.get("repeat", "none") == "none" and is_outdated(reminder):
                    continue
                
                # 生成唯一的任务ID
                job_id = f"reminder_{group}_{i}"
                
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
                elif reminder.get("repeat") == "daily_workday":
                    # 每个工作日重复
                    self.scheduler.add_job(
                        self._check_and_execute_workday,
                        'cron',
                        args=[group, reminder],
                        hour=dt.hour,
                        minute=dt.minute,
                        day_of_week='mon-fri',  # 先按周一到周五执行，后续再判断法定节假日
                        misfire_grace_time=60,
                        id=job_id
                    )
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
                elif reminder.get("repeat") == "weekly_workday":
                    # 每周的这一天，但仅工作日执行
                    self.scheduler.add_job(
                        self._check_and_execute_workday,
                        'cron',
                        args=[group, reminder],
                        day_of_week=dt.weekday(),
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
                        args=[group, reminder],
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
                        args=[group, reminder],
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
                        args=[group, reminder],
                        day=dt.day,
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
                        args=[group, reminder],
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
                        args=[group, reminder],
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
                        args=[group, reminder],
                        month=dt.month,
                        day=dt.day,
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
                        args=[group, reminder],
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
                        args=[group, reminder],
                        run_date=dt,
                        misfire_grace_time=60,
                        id=job_id
                    )
    
    async def _check_and_execute_workday(self, unified_msg_origin: str, reminder: dict):
        '''检查当天是否为工作日，如果是则执行提醒'''
        today = datetime.datetime.now()
        is_workday = await self.holiday_manager.is_workday(today)
        
        if is_workday:
            # 如果是工作日则执行提醒
            await self._reminder_callback(unified_msg_origin, reminder)
        else:
            logger.info(f"今天不是工作日，跳过执行提醒: {reminder['text']}")
    
    async def _check_and_execute_holiday(self, unified_msg_origin: str, reminder: dict):
        '''检查当天是否为法定节假日，如果是则执行提醒'''
        today = datetime.datetime.now()
        is_holiday = await self.holiday_manager.is_holiday(today)
        
        if is_holiday:
            # 如果是法定节假日则执行提醒
            await self._reminder_callback(unified_msg_origin, reminder)
        else:
            logger.info(f"今天不是法定节假日，跳过执行提醒: {reminder['text']}")
    
    async def _reminder_callback(self, unified_msg_origin: str, reminder: dict):
        '''提醒回调函数'''
        provider = self.context.get_using_provider()
        
        # 区分提醒和任务
        is_task = reminder.get("is_task", False)
        
        # 判断是否为私聊（根据实际消息格式精确判断）
        is_private_chat = (":FriendMessage:" in unified_msg_origin)  # 适用于QQ和微信
        is_group_chat = (":GroupMessage:" in unified_msg_origin) or ("@chatroom" in unified_msg_origin)  # 群聊判断
        
        if provider:
            if is_task:
                # 任务模式：模拟用户发送消息，让AI执行任务
                task_text = reminder['text']
                logger.info(f"Task Activated: {task_text}, attempting to execute for {unified_msg_origin}")
                
                # 检查是否是调用LLM函数的任务
                if task_text.startswith("请调用") and "函数" in task_text:
                    # 这是一个请求调用LLM函数的任务
                    # 我们需要直接告诉AI执行这个任务，而不是作为普通消息处理
                    prompt = f"用户请求你执行以下操作：{task_text}。请直接执行这个任务，不要解释你在做什么，就像用户刚刚发出这个请求一样。"
                else:
                    # 普通任务，直接让AI执行
                    prompt = f"请执行以下任务：{task_text}。这是用户之前设置的定时任务，现在需要你执行。请直接执行，不要提及这是一个预设任务。"
                
                response = await provider.text_chat(
                    prompt=prompt,
                    session_id=unified_msg_origin,
                    contexts=[]
                )
                
                # 构建消息链
                result_msg = MessageChain()
                result_msg.chain.append(Plain(response.completion_text))
                
                await self.context.send_message(unified_msg_origin, result_msg)
                logger.info(f"Task executed: {task_text}")
            else:
                # 提醒模式：只是提醒用户
                prompt = f"你现在在和{reminder['user_name']}对话，发出提醒给他，提醒内容是'{reminder['text']}'。直接发出对话内容，就是你说的话，不要有其他的背景描述。"
                
                response = await provider.text_chat(
                    prompt=prompt,
                    session_id=unified_msg_origin,
                    contexts=[]  # 确保contexts是一个空列表而不是None
                )
                logger.info(f"Reminder Activated: {reminder['text']}, created by {unified_msg_origin}")
                
                # 构建消息链
                msg = MessageChain()
                
                # 如果不是私聊且存在创建者ID，则添加@（明确使用私聊判断）
                if not is_private_chat and "creator_id" in reminder and reminder["creator_id"]:
                    if unified_msg_origin.startswith("aiocqhttp"):
                        msg.chain.append(At(qq=reminder["creator_id"]))  # QQ平台
                    elif unified_msg_origin.startswith("gewechat"):
                        # 微信平台 - 使用用户名/昵称而不是ID
                        if "creator_name" in reminder and reminder["creator_name"]:
                            msg.chain.append(At(qq=reminder["creator_id"], name=reminder["creator_name"]))
                        else:
                            # 如果没有保存用户名，尝试使用ID
                            msg.chain.append(At(qq=reminder["creator_id"]))
                    else:
                        # 其他平台的@实现
                        msg.chain.append(Plain(f"@{reminder['creator_id']} "))
                
                # 提醒需要[提醒]前缀
                msg.chain.append(Plain("[提醒]" + response.completion_text))
                
                await self.context.send_message(unified_msg_origin, msg)
        else:
            # 构建基础消息链
            msg = MessageChain()
            
            # 如果不是私聊且存在创建者ID，则添加@（明确使用私聊判断）
            if not is_private_chat and "creator_id" in reminder and reminder["creator_id"]:
                if unified_msg_origin.startswith("aiocqhttp"):
                    msg.chain.append(At(qq=reminder["creator_id"]))  # QQ平台
                elif unified_msg_origin.startswith("gewechat"):
                    # 微信平台 - 使用用户名/昵称而不是ID
                    if "creator_name" in reminder and reminder["creator_name"]:
                        msg.chain.append(At(qq=reminder["creator_id"], name=reminder["creator_name"]))
                    else:
                        # 如果没有保存用户名，尝试使用ID
                        msg.chain.append(At(qq=reminder["creator_id"]))
                else:
                    # 其他平台的@实现
                    msg.chain.append(Plain(f"@{reminder['creator_id']} "))
            
            prefix = "任务: " if is_task else "提醒: "
            msg.chain.append(Plain(f"{prefix}{reminder['text']}"))
            
            await self.context.send_message(unified_msg_origin, msg)
            
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
                day_of_week='mon-fri',  # 先按周一到周五执行，后续再判断法定节假日
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
                day_of_week=dt.weekday(),
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
                day=dt.day,
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
                month=dt.month,
                day=dt.day,
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