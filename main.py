from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import *
from astrbot.api.event.filter import command, command_group
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers.base import JobLookupError
from astrbot.api import logger
from astrbot.api.event import MessageChain
import datetime
import json
import os
from typing import Union

@register("ai_reminder", "kjqwdw", "智能定时任务，输入/rmd help查看帮助", "1.0.1")
class SmartReminder(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.scheduler = AsyncIOScheduler()
        
        # 使用插件目录下的数据文件
        plugin_dir = os.path.dirname(os.path.abspath(__file__))  # 获取当前文件所在目录
        self.data_file = os.path.join(plugin_dir, "reminder.json")
        
        # 初始化数据存储
        if not os.path.exists(self.data_file):
            with open(self.data_file, "w", encoding='utf-8') as f:
                f.write("{}")
        with open(self.data_file, "r", encoding='utf-8') as f:
            self.reminder_data = json.load(f)
        
        self._init_scheduler()
        self.scheduler.start()

    def _init_scheduler(self):
        '''初始化定时器'''
        for group in self.reminder_data:
            for i, reminder in enumerate(self.reminder_data[group]):
                if "datetime" not in reminder:
                    continue
                
                if reminder.get("repeat", "none") == "none" and self._is_outdated(reminder):
                    continue
                
                dt = datetime.datetime.strptime(reminder["datetime"], "%Y-%m-%d %H:%M")
                
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
                else:
                    self.scheduler.add_job(
                        self._reminder_callback,
                        'date',
                        args=[group, reminder],
                        run_date=dt,
                        misfire_grace_time=60,
                        id=job_id
                    )

    def _is_outdated(self, reminder: dict):
        '''检查提醒是否过期'''
        if "datetime" in reminder:
            return datetime.datetime.strptime(reminder["datetime"], "%Y-%m-%d %H:%M") < datetime.datetime.now()
        return False

    async def _save_data(self):
        '''保存提醒数据'''
        with open(self.data_file, "w", encoding='utf-8') as f:
            json.dump(self.reminder_data, f, ensure_ascii=False)

    @filter.llm_tool(name="set_reminder")
    async def set_reminder(self, event: Union[AstrMessageEvent, Context], text: str, datetime_str: str, user_name: str = "用户", repeat: str = None):
        '''设置一个定时任务，这个任务可以是提醒，也可以是让作为执行者的自己做一件事
        
        Args:
            text(string): 任务内容
            datetime_str(string): 任务时间，格式为 %Y-%m-%d %H:%M
            user_name(string): 对象名称，任务享受者，默认为"用户"
            repeat(string): 重复类型，可选值：daily(每天)，weekly(每周)，monthly(每月)，yearly(每年)，none(不重复)
        '''
        try:
            if isinstance(event, Context):
                msg_origin = self.context.get_event_queue()._queue[0].session_id
                creator_id = None  # Context 模式下无法获取创建者ID
            else:
                msg_origin = event.unified_msg_origin
                creator_id = event.get_sender_id() if event.message_obj.group_id else None
            
            if msg_origin not in self.reminder_data:
                self.reminder_data[msg_origin] = []
            
            reminder = {
                "text": text,
                "datetime": datetime_str,
                "user_name": user_name,
                "repeat": repeat or "none",
                "creator_id": creator_id  # 新增：存储创建者ID
            }
            
            self.reminder_data[msg_origin].append(reminder)
            
            # 解析时间
            dt = datetime.datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
            
            # 根据重复类型设置不同的触发器
            if repeat == "daily":
                self.scheduler.add_job(
                    self._reminder_callback,
                    'cron',
                    args=[msg_origin, reminder],
                    hour=dt.hour,
                    minute=dt.minute,
                    misfire_grace_time=60,
                    id=f"reminder_{msg_origin}_{len(self.reminder_data[msg_origin])-1}"
                )
            elif repeat == "weekly":
                self.scheduler.add_job(
                    self._reminder_callback,
                    'cron',
                    args=[msg_origin, reminder],
                    day_of_week=dt.weekday(),
                    hour=dt.hour,
                    minute=dt.minute,
                    misfire_grace_time=60,
                    id=f"reminder_{msg_origin}_{len(self.reminder_data[msg_origin])-1}"
                )
            elif repeat == "monthly":
                self.scheduler.add_job(
                    self._reminder_callback,
                    'cron',
                    args=[msg_origin, reminder],
                    day=dt.day,
                    hour=dt.hour,
                    minute=dt.minute,
                    misfire_grace_time=60,
                    id=f"reminder_{msg_origin}_{len(self.reminder_data[msg_origin])-1}"
                )
            elif repeat == "yearly":
                self.scheduler.add_job(
                    self._reminder_callback,
                    'cron',
                    args=[msg_origin, reminder],
                    month=dt.month,
                    day=dt.day,
                    hour=dt.hour,
                    minute=dt.minute,
                    misfire_grace_time=60,
                    id=f"reminder_{msg_origin}_{len(self.reminder_data[msg_origin])-1}"
                )
            else:
                self.scheduler.add_job(
                    self._reminder_callback,
                    'date',
                    args=[msg_origin, reminder],
                    run_date=dt,
                    misfire_grace_time=60,
                    id=f"reminder_{msg_origin}_{len(self.reminder_data[msg_origin])-1}"
                )
            
            await self._save_data()
            
            repeat_str = ""
            if repeat == "daily":
                repeat_str = "，每天重复"
            elif repeat == "weekly":
                repeat_str = "，每周重复"
            elif repeat == "monthly":
                repeat_str = "，每月重复"
            elif repeat == "yearly":
                repeat_str = "，每年重复"
            
            return f"已设置任务:\n内容: {text}\n时间: {datetime_str}{repeat_str}\n\n使用 /rmd ls 查看所有任务"
            
        except Exception as e:
            return f"设置任务时出错：{str(e)}"

    async def _reminder_callback(self, unified_msg_origin: str, reminder: dict):
        '''提醒回调函数'''
        provider = self.context.get_using_provider()
        if provider:
            # 构建提醒消息
            prompt = f"你现在在和{reminder['user_name']}对话，发出提醒给他，提醒内容是'{reminder['text']}'，如果提醒内容是要求你做事，比如讲故事，你就执行。直接发出对话内容，就是你说的话，不要有其他的背景描述。"
            response = await provider.text_chat(
                prompt=prompt,
                session_id=unified_msg_origin
            )
            logger.info(f"Reminder Activated: {reminder['text']}, created by {unified_msg_origin}")
            
            # 构建消息链
            msg = MessageChain()
            
            # 如果存在创建者ID，则添加@
            if "creator_id" in reminder and reminder["creator_id"]:
                if ":" in unified_msg_origin and unified_msg_origin.startswith("aiocqhttp"):
                    msg.chain.append(At(qq=reminder["creator_id"]))  # QQ平台
                else:
                    # 其他平台的@实现
                    msg.chain.append(Plain(f"@{reminder['creator_id']} "))
            
            msg.chain.append(Plain("[提醒]" + response.completion_text))
            
            await self.context.send_message(unified_msg_origin, msg)
        else:
            # 构建基础消息链
            msg = MessageChain()
            
            # 如果存在创建者ID，则添加@
            if "creator_id" in reminder and reminder["creator_id"]:
                if ":" in unified_msg_origin and unified_msg_origin.startswith("aiocqhttp"):
                    msg.chain.append(At(qq=reminder["creator_id"]))  # QQ平台
                else:
                    # 其他平台的@实现
                    msg.chain.append(Plain(f"@{reminder['creator_id']} "))
            
            msg.chain.append(Plain(f"提醒: {reminder['text']}"))
            
            await self.context.send_message(unified_msg_origin, msg)

    @command_group("rmd")
    def rmd(self):
        '''提醒相关命令'''
        pass

    @rmd.command("ls")
    async def list_reminders(self, event: AstrMessageEvent):
        '''列出所有提醒'''
        reminders = self.reminder_data.get(event.unified_msg_origin, [])
        if not reminders:
            yield event.plain_result("当前没有设置任何任务。")
            return
            
        provider = self.context.get_using_provider()
        if provider:
            try:
                reminder_list = "\n".join([f"- {r['text']} (时间: {r['datetime']})" for r in reminders])
                prompt = f"请帮我整理并展示以下任务列表，用自然的语言表达：\n{reminder_list}\n同时告诉用户可以使用/rmd rm <序号>或者直接命令自己来删除提醒。直接发出对话内容，就是你说的话，不要有其他的背景描述。"
                response = await provider.text_chat(
                    prompt=prompt,
                    session_id=event.session_id,
                    contexts=[]  # 确保contexts是一个空列表而不是None
                )
                yield event.plain_result(response.completion_text)
            except Exception as e:
                logger.error(f"在list_reminders中调用LLM时出错: {str(e)}")
                # 如果LLM调用失败，回退到基本显示
                reminder_str = "当前的任务：\n"
                for i, reminder in enumerate(reminders):
                    reminder_str += f"{i+1}. {reminder['text']} - {reminder['datetime']}\n"
                reminder_str += "\n使用 /rmd rm <序号> 删除任务"
                yield event.plain_result(reminder_str)
        else:
            reminder_str = "当前的任务：\n"
            for i, reminder in enumerate(reminders):
                reminder_str += f"{i+1}. {reminder['text']} - {reminder['datetime']}\n"
            reminder_str += "\n使用 /rmd rm <序号> 删除任务"
            yield event.plain_result(reminder_str)

    @rmd.command("rm")
    async def remove_reminder(self, event: AstrMessageEvent, index: int):
        '''删除任务
        
        Args:
            index(int): 任务的序号
        '''
        reminders = self.reminder_data.get(event.unified_msg_origin, [])
        if not reminders:
            yield event.plain_result("没有设置任何任务。")
            return
            
        if index < 1 or index > len(reminders):
            yield event.plain_result("任务序号无效。")
            return
            
        # 删除调度任务
        job_id = f"reminder_{event.unified_msg_origin}_{index-1}"
        try:
            self.scheduler.remove_job(job_id)
            logger.info(f"Successfully removed job: {job_id}")
        except JobLookupError:
            logger.error(f"Job not found: {job_id}")
            
        removed = reminders.pop(index - 1)
        await self._save_data()
        
        provider = self.context.get_using_provider()
        if provider:
            prompt = f"用户删除了一个任务，内容是'{removed['text']}'。请用自然的语言确认删除操作。直接发出对话内容，就是你说的话，不要有其他的背景描述。"
            response = await provider.text_chat(
                prompt=prompt,
                session_id=event.session_id
            )
            yield event.plain_result(response.completion_text)
        else:
            yield event.plain_result(f"已删除任务：{removed['text']}")

    @rmd.command("add")
    async def add_reminder(self, event: AstrMessageEvent, text: str, time_str: str, week: str = None, repeat: str = None):
        '''手动添加提醒
        
        Args:
            text(string): 提醒内容
            time_str(string): 时间，格式为 HH:MM 或 HHMM
            week(string): 可选，开始星期：mon,tue,wed,thu,fri,sat,sun
            repeat(string): 可选，重复类型：daily,weekly,monthly,yearly
        '''
        try:
            # 解析时间
            try:
                datetime_str = self._parse_datetime(time_str)
            except ValueError as e:
                yield event.plain_result(str(e))
                return

            # 验证星期格式
            week_map = {
                'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 
                'fri': 4, 'sat': 5, 'sun': 6
            }
            
            if week and week.lower() not in week_map:
                yield event.plain_result("星期格式错误，可选值：mon,tue,wed,thu,fri,sat,sun")
                return

            # 验证重复类型
            repeat_types = ["daily", "weekly", "monthly", "yearly"]
            if repeat and repeat.lower() not in repeat_types:
                yield event.plain_result("重复类型错误，可选值：daily,weekly,monthly,yearly")
                return

            msg_origin = event.unified_msg_origin
            creator_id = event.get_sender_id()
            
            if msg_origin not in self.reminder_data:
                self.reminder_data[msg_origin] = []
            
            dt = datetime.datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
            
            # 如果指定了星期，调整到下一个符合的日期
            if week:
                target_weekday = week_map[week.lower()]
                current_weekday = dt.weekday()
                days_ahead = target_weekday - current_weekday
                if days_ahead <= 0:  # 如果目标星期已过，调整到下周
                    days_ahead += 7
                dt += datetime.timedelta(days=days_ahead)
            
            reminder = {
                "text": text,
                "datetime": dt.strftime("%Y-%m-%d %H:%M"),
                "user_name": creator_id,
                "repeat": repeat.lower() if repeat else "none",
                "creator_id": creator_id
            }
            
            self.reminder_data[msg_origin].append(reminder)
            
            # 生成任务ID
            job_id = f"reminder_{msg_origin}_{len(self.reminder_data[msg_origin])-1}"
            
            # 设置定时任务
            if repeat == "daily":
                self.scheduler.add_job(
                    self._reminder_callback,
                    'cron',
                    args=[msg_origin, reminder],
                    hour=dt.hour,
                    minute=dt.minute,
                    misfire_grace_time=60,
                    id=job_id
                )
            elif repeat == "weekly":
                self.scheduler.add_job(
                    self._reminder_callback,
                    'cron',
                    args=[msg_origin, reminder],
                    day_of_week=dt.weekday(),  # 使用调整后的星期
                    hour=dt.hour,
                    minute=dt.minute,
                    misfire_grace_time=60,
                    id=job_id
                )
            elif repeat == "monthly":
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
            elif repeat == "yearly":
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
            else:
                self.scheduler.add_job(
                    self._reminder_callback,
                    'date',
                    args=[msg_origin, reminder],
                    run_date=dt,
                    misfire_grace_time=60,
                    id=job_id
                )
            
            await self._save_data()
            
            # 生成提示信息
            week_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
            start_str = f"从{week_names[dt.weekday()]}开始，" if week else ""
            
            if repeat == "daily":
                repeat_str = "每天重复"
            elif repeat == "weekly":
                repeat_str = "每周重复"
            elif repeat == "monthly":
                repeat_str = "每月重复"
            elif repeat == "yearly":
                repeat_str = "每年重复"
            else:
                repeat_str = "一次性提醒"
            
            yield event.plain_result(f"已设置提醒:\n内容: {text}\n时间: {dt.strftime('%Y-%m-%d %H:%M')}\n{start_str}{repeat_str}\n\n使用 /rmd ls 查看所有提醒")
            
        except Exception as e:
            yield event.plain_result(f"设置提醒时出错：{str(e)}")

    @rmd.command("help")
    async def show_help(self, event: AstrMessageEvent):
        '''显示帮助信息'''
        help_text = """提醒功能指令说明：
1. 手动添加提醒：
   /rmd add <内容> <时间> [开始星期] [重复类型]
   例如：
   - /rmd add 写周报 8:05
   - /rmd add 吃饭 8:05 sun daily (从周日开始每天)
   - /rmd add 开会 8:05 mon weekly (每周一)
   - /rmd add 交房租 8:05 fri monthly (从周五开始每月)

2. 查看提醒：
   /rmd ls - 列出所有提醒

3. 删除提醒：
   /rmd rm <序号> - 删除指定提醒

4. 星期可选值：
   - mon: 周一
   - tue: 周二
   - wed: 周三
   - thu: 周四
   - fri: 周五
   - sat: 周六
   - sun: 周日

5. 重复类型：
   - daily: 每天重复
   - weekly: 每周重复
   - monthly: 每月重复
   - yearly: 每年重复

6.ai智能提醒
  正常对话即可，ai会自己设置提醒，但是需要ai支持llm

注：时间格式为 HH:MM 或 HHMM，如 8:05 或 0805"""
        yield event.plain_result(help_text)

    def _parse_datetime(self, datetime_str: str) -> str:
        '''解析时间字符串，支持简单时间格式，可选择星期'''
        try:
            today = datetime.datetime.now()
            
            # 处理输入字符串，去除多余空格
            datetime_str = datetime_str.strip()
            
            # 解析时间
            try:
                hour, minute = map(int, datetime_str.split(':'))
            except ValueError:
                try:
                    # 尝试处理无冒号格式 (如 "0805")
                    if len(datetime_str) == 4:
                        hour = int(datetime_str[:2])
                        minute = int(datetime_str[2:])
                    else:
                        raise ValueError()
                except:
                    raise ValueError("时间格式错误，请使用 HH:MM 格式（如 8:05）或 HHMM 格式（如 0805）")
            
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("时间超出范围")
                
            # 设置时间
            dt = today.replace(hour=hour, minute=minute)
            if dt < today:  # 如果时间已过，设置为明天
                dt += datetime.timedelta(days=1)
            
            return dt.strftime("%Y-%m-%d %H:%M")
            
        except Exception as e:
            if isinstance(e, ValueError):
                raise e
            raise ValueError("时间格式错误，请使用 HH:MM 格式（如 8:05）或 HHMM 格式（如 0805）")

    @filter.llm_tool(name="delete_reminder")
    async def delete_reminder(self, event: Union[AstrMessageEvent, Context], 
                            content: str = None,           # 任务内容关键词
                            time: str = None,              # 具体时间点 HH:MM
                            weekday: str = None,           # 星期 mon,tue,wed,thu,fri,sat,sun
                            repeat_type: str = None,       # 重复类型 daily,weekly,monthly,yearly
                            date: str = None,              # 具体日期 YYYY-MM-DD
                            all: str = None                # 是否删除所有 "yes"/"no"
                            ):
        '''删除符合条件的提醒任务，可组合多个条件进行精确筛选
        
        Args:
            content(string): 可选，任务内容包含的关键词
            time(string): 可选，具体时间点，格式为 HH:MM，如 "08:00"
            weekday(string): 可选，星期几，可选值：mon,tue,wed,thu,fri,sat,sun
            repeat_type(string): 可选，重复类型，可选值：daily,weekly,monthly,yearly
            date(string): 可选，具体日期，格式为 YYYY-MM-DD，如 "2024-02-09"
            all(string): 可选，是否删除所有任务，可选值：yes/no，默认no
        '''
        try:
            if isinstance(event, Context):
                msg_origin = self.context.get_event_queue()._queue[0].session_id
            else:
                msg_origin = event.unified_msg_origin
            
            # 调试信息：打印所有调度任务
            logger.info("Current jobs in scheduler:")
            for job in self.scheduler.get_jobs():
                logger.info(f"Job ID: {job.id}, Next run: {job.next_run_time}, Args: {job.args}")
            
            reminders = self.reminder_data.get(msg_origin, [])
            if not reminders:
                return "当前没有任何任务。"
            
            # 用于存储要删除的任务索引
            to_delete = []
            
            # 验证星期格式
            week_map = {
                'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 
                'fri': 4, 'sat': 5, 'sun': 6
            }
            if weekday and weekday.lower() not in week_map:
                return "星期格式错误，可选值：mon,tue,wed,thu,fri,sat,sun"
            
            # 验证重复类型
            repeat_types = ["daily", "weekly", "monthly", "yearly"]
            if repeat_type and repeat_type.lower() not in repeat_types:
                return "重复类型错误，可选值：daily,weekly,monthly,yearly"
            
            for i, reminder in enumerate(reminders):
                dt = datetime.datetime.strptime(reminder["datetime"], "%Y-%m-%d %H:%M")
                
                # 如果指定删除所有，直接添加
                if all and all.lower() == "yes":
                    to_delete.append(i)
                    continue
                
                # 检查各个条件，所有指定的条件都必须满足
                match = True
                
                # 检查内容
                if content and content not in reminder["text"]:
                    match = False
                
                # 检查时间点
                if time:
                    reminder_time = dt.strftime("%H:%M")
                    if reminder_time != time:
                        match = False
                
                # 检查星期
                if weekday:
                    if reminder.get("repeat") == "weekly":
                        # 对于每周重复的任务，检查是否在指定星期执行
                        if dt.weekday() != week_map[weekday.lower()]:
                            match = False
                    else:
                        # 对于非每周重复的任务，检查日期是否落在指定星期
                        if dt.weekday() != week_map[weekday.lower()]:
                            match = False
                
                # 检查重复类型
                if repeat_type and reminder.get("repeat") != repeat_type.lower():
                    match = False
                
                # 检查具体日期
                if date:
                    reminder_date = dt.strftime("%Y-%m-%d")
                    if reminder_date != date:
                        match = False
                
                # 如果所有条件都满足，添加到删除列表
                if match:
                    to_delete.append(i)
            
            if not to_delete:
                conditions = []
                if content:
                    conditions.append(f"内容包含{content}")
                if time:
                    conditions.append(f"时间为{time}")
                if weekday:
                    conditions.append(f"在{weekday}")
                if repeat_type:
                    conditions.append(f"重复类型为{repeat_type}")
                if date:
                    conditions.append(f"日期为{date}")
                return f"没有找到符合条件的任务：{', '.join(conditions)}"
            
            # 从后往前删除，避免索引变化
            deleted_reminders = []
            for i in sorted(to_delete, reverse=True):
                reminder = reminders[i]
                
                # 调试信息：打印正在删除的任务
                logger.info(f"Attempting to delete reminder: {reminder}")
                
                # 尝试删除调度任务
                job_id = f"reminder_{msg_origin}_{i}"
                try:
                    self.scheduler.remove_job(job_id)
                    logger.info(f"Successfully removed job: {job_id}")
                except JobLookupError:
                    logger.error(f"Job not found: {job_id}")
                
                # 以防万一，也检查其他可能的任务
                for job in self.scheduler.get_jobs():
                    if len(job.args) >= 2 and isinstance(job.args[1], dict):
                        job_reminder = job.args[1]
                        if (job_reminder.get('text') == reminder['text'] and 
                            job_reminder.get('datetime') == reminder['datetime']):
                            try:
                                logger.info(f"Removing additional job: {job.id}")
                                job.remove()
                            except Exception as e:
                                logger.error(f"Error removing additional job {job.id}: {str(e)}")
                
                deleted_reminders.append(reminder)
                reminders.pop(i)
            
            # 更新数据
            self.reminder_data[msg_origin] = reminders
            await self._save_data()
            
            # 调试信息：打印剩余的调度任务
            logger.info("Remaining jobs in scheduler:")
            for job in self.scheduler.get_jobs():
                logger.info(f"Job ID: {job.id}, Next run: {job.next_run_time}, Args: {job.args}")
            
            # 生成删除报告
            if len(deleted_reminders) == 1:
                return f"已删除任务：{deleted_reminders[0]['text']}"
            else:
                tasks = "\n".join([f"- {r['text']}" for r in deleted_reminders])
                return f"已删除以下 {len(deleted_reminders)} 个任务：\n{tasks}"
            
        except Exception as e:
            return f"删除任务时出错：{str(e)}"