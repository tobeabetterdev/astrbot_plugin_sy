from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import *
from astrbot.api.event.filter import command, command_group
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers.base import JobLookupError
from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import MessageChain
import datetime
import json
import os
from typing import Union

from .utils import load_reminder_data, parse_datetime, save_reminder_data, is_outdated
from .scheduler import ReminderScheduler
from .tools import ReminderTools

@register("ai_reminder", "kjqwdw", "智能定时任务，输入/rmd help查看帮助", "1.0.10")
class SmartReminder(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        
        # 保存配置
        self.config = config or {}
        self.unique_session = self.config.get("unique_session", False)
        
        # 使用data目录下的数据文件，而非插件自身目录
        data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")
        # 确保目录存在
        os.makedirs(os.path.join(data_dir, "reminders"), exist_ok=True)
        self.data_file = os.path.join(data_dir, "reminders", "reminder_data.json")
        
        # 初始化数据存储
        self.reminder_data = load_reminder_data(self.data_file)
        
        # 初始化调度器
        self.scheduler_manager = ReminderScheduler(context, self.reminder_data, self.data_file, self.unique_session)
        
        # 初始化工具
        self.tools = ReminderTools(self)
        
        # 记录配置信息
        logger.info(f"智能提醒插件启动成功，会话隔离：{'启用' if self.unique_session else '禁用'}")

    @filter.llm_tool(name="set_reminder")
    async def set_reminder(self, event, text: str, datetime_str: str, user_name: str = "用户", repeat: str = None, holiday_type: str = None):
        '''设置一个提醒，到时间后会提醒用户
        
        Args:
            text(string): 提醒内容
            datetime_str(string): 提醒时间，格式为 %Y-%m-%d %H:%M
            user_name(string): 提醒对象名称，默认为"用户"
            repeat(string): 重复类型，可选值：daily(每天)，weekly(每周)，monthly(每月)，yearly(每年)，none(不重复)
            holiday_type(string): 可选，节假日类型：workday(仅工作日执行)，holiday(仅法定节假日执行)
        '''
        return await self.tools.set_reminder(event, text, datetime_str, user_name, repeat, holiday_type)

    @filter.llm_tool(name="set_task")
    async def set_task(self, event, text: str, datetime_str: str, repeat: str = None, holiday_type: str = None):
        '''设置一个任务，到时间后会让AI执行该任务
        
        Args:
            text(string): 任务内容，AI将执行的操作，如果是调用其他llm函数，请告诉ai（比如，请调用llm函数，内容是...）
            datetime_str(string): 任务执行时间，格式为 %Y-%m-%d %H:%M
            repeat(string): 重复类型，可选值：daily(每天)，weekly(每周)，monthly(每月)，yearly(每年)，none(不重复)
            holiday_type(string): 可选，节假日类型：workday(仅工作日执行)，holiday(仅法定节假日执行)
        '''
        return await self.tools.set_task(event, text, datetime_str, repeat, holiday_type)

    @filter.llm_tool(name="delete_reminder")
    async def delete_reminder(self, event, 
                            content: str = None,           # 提醒内容关键词
                            time: str = None,              # 具体时间点 HH:MM
                            weekday: str = None,           # 星期 mon,tue,wed,thu,fri,sat,sun
                            repeat_type: str = None,       # 重复类型 daily,weekly,monthly,yearly
                            date: str = None,              # 具体日期 YYYY-MM-DD
                            all: str = None,               # 是否删除所有 "yes"/"no"
                            task_only: str = "no"          # 是否只删除任务 "yes"/"no"
                            ):
        '''删除符合条件的提醒，可组合多个条件进行精确筛选
        
        Args:
            content(string): 可选，提醒内容包含的关键词
            time(string): 可选，具体时间点，格式为 HH:MM，如 "08:00"
            weekday(string): 可选，星期几，可选值：mon,tue,wed,thu,fri,sat,sun
            repeat_type(string): 可选，重复类型，可选值：daily,weekly,monthly,yearly
            date(string): 可选，具体日期，格式为 YYYY-MM-DD，如 "2024-02-09"
            all(string): 可选，是否删除所有提醒，可选值：yes/no，默认no
            task_only(string): 可选，是否只删除任务，可选值：yes/no，默认no
        '''
        is_task_only = task_only and task_only.lower() == "yes"
        return await self.tools.delete_reminder(event, content, time, weekday, repeat_type, date, all, is_task_only, "no")

    @filter.llm_tool(name="delete_task")
    async def delete_task(self, event, 
                        content: str = None,           # 任务内容关键词
                        time: str = None,              # 具体时间点 HH:MM
                        weekday: str = None,           # 星期 mon,tue,wed,thu,fri,sat,sun
                        repeat_type: str = None,       # 重复类型 daily,weekly,monthly,yearly
                        date: str = None,              # 具体日期 YYYY-MM-DD
                        all: str = None                # 是否删除所有 "yes"/"no"
                        ):
        '''删除符合条件的任务，可组合多个条件进行精确筛选
        
        Args:
            content(string): 可选，任务内容包含的关键词
            time(string): 可选，具体时间点，格式为 HH:MM，如 "08:00"
            weekday(string): 可选，星期几，可选值：mon,tue,wed,thu,fri,sat,sun
            repeat_type(string): 可选，重复类型，可选值：daily,weekly,monthly,yearly
            date(string): 可选，具体日期，格式为 YYYY-MM-DD，如 "2024-02-09"
            all(string): 可选，是否删除所有任务，可选值：yes/no，默认no
        '''
        return await self.tools.delete_reminder(event, content, time, weekday, repeat_type, date, all, "yes", "no")
        
    # 命令组必须定义在主类中
    @command_group("rmd")
    def rmd(self):
        '''提醒相关命令'''
        pass

    @rmd.command("ls")
    async def list_reminders(self, event: AstrMessageEvent):
        '''列出所有提醒和任务'''
        # 获取用户ID，用于会话隔离
        creator_id = event.get_sender_id()
        
        # 获取会话ID
        raw_msg_origin = event.unified_msg_origin
        if self.unique_session:
            # 使用会话隔离
            msg_origin = self.tools.get_session_id(raw_msg_origin, creator_id)
        else:
            msg_origin = raw_msg_origin
            
        reminders = self.reminder_data.get(msg_origin, [])
        if not reminders:
            yield event.plain_result("当前没有设置任何提醒或任务。")
            return
            
        provider = self.context.get_using_provider()
        if provider:
            try:
                # 分离提醒和任务
                reminder_items = []
                task_items = []
                
                for r in reminders:
                    if r.get("is_task", False):
                        task_items.append(f"- {r['text']} (时间: {r['datetime']})")
                    else:
                        reminder_items.append(f"- {r['text']} (时间: {r['datetime']})")
                
                # 构建提示
                prompt = "请帮我整理并展示以下提醒和任务列表，用自然的语言表达：\n"
                
                if reminder_items:
                    prompt += f"\n提醒列表：\n" + "\n".join(reminder_items)
                
                if task_items:
                    prompt += f"\n\n任务列表：\n" + "\n".join(task_items)
                
                prompt += "\n\n同时告诉用户可以使用/rmd rm <序号>删除提醒或任务，或者直接命令你来删除。直接发出对话内容，就是你说的话，不要有其他的背景描述。"
                
                response = await provider.text_chat(
                    prompt=prompt,
                    session_id=event.session_id,
                    contexts=[]  # 确保contexts是一个空列表而不是None
                )
                yield event.plain_result(response.completion_text)
            except Exception as e:
                logger.error(f"在list_reminders中调用LLM时出错: {str(e)}")
                # 如果LLM调用失败，回退到基本显示
                reminder_str = "当前的提醒和任务：\n"
                
                # 分类显示
                reminders_list = [r for r in reminders if not r.get("is_task", False)]
                tasks_list = [r for r in reminders if r.get("is_task", False)]
                
                if reminders_list:
                    reminder_str += "\n提醒：\n"
                    for i, reminder in enumerate(reminders_list):
                        reminder_str += f"{i+1}. {reminder['text']} - {reminder['datetime']}\n"
                
                if tasks_list:
                    reminder_str += "\n任务：\n"
                    for i, task in enumerate(tasks_list):
                        reminder_str += f"{len(reminders_list)+i+1}. {task['text']} - {task['datetime']}\n"
                
                reminder_str += "\n使用 /rmd rm <序号> 删除提醒或任务"
                yield event.plain_result(reminder_str)
        else:
            reminder_str = "当前的提醒和任务：\n"
            
            # 分类显示
            reminders_list = [r for r in reminders if not r.get("is_task", False)]
            tasks_list = [r for r in reminders if r.get("is_task", False)]
            
            if reminders_list:
                reminder_str += "\n提醒：\n"
                for i, reminder in enumerate(reminders_list):
                    reminder_str += f"{i+1}. {reminder['text']} - {reminder['datetime']}\n"
            
            if tasks_list:
                reminder_str += "\n任务：\n"
                for i, task in enumerate(tasks_list):
                    reminder_str += f"{len(reminders_list)+i+1}. {task['text']} - {task['datetime']}\n"
            
            reminder_str += "\n使用 /rmd rm <序号> 删除提醒或任务"
            yield event.plain_result(reminder_str)

    @rmd.command("rm")
    async def remove_reminder(self, event: AstrMessageEvent, index: int):
        '''删除提醒或任务
        
        Args:
            index(int): 提醒或任务的序号
        '''
        # 获取用户ID，用于会话隔离
        creator_id = event.get_sender_id()
        
        # 获取会话ID
        raw_msg_origin = event.unified_msg_origin
        if self.unique_session:
            # 使用会话隔离
            msg_origin = self.tools.get_session_id(raw_msg_origin, creator_id)
        else:
            msg_origin = raw_msg_origin
            
        reminders = self.reminder_data.get(msg_origin, [])
        if not reminders:
            yield event.plain_result("没有设置任何提醒或任务。")
            return
            
        if index < 1 or index > len(reminders):
            yield event.plain_result("序号无效。")
            return
            
        # 获取要删除的提醒或任务
        job_id = f"reminder_{msg_origin}_{index-1}"
        
        # 尝试删除调度任务
        try:
            self.scheduler_manager.remove_job(job_id)
            logger.info(f"Successfully removed job: {job_id}")
        except JobLookupError:
            logger.error(f"Job not found: {job_id}")
            
        removed = reminders.pop(index - 1)
        await save_reminder_data(self.data_file, self.reminder_data)
        
        is_task = removed.get("is_task", False)
        item_type = "任务" if is_task else "提醒"
        
        provider = self.context.get_using_provider()
        if provider:
            prompt = f"用户删除了一个{item_type}，内容是'{removed['text']}'。请用自然的语言确认删除操作。直接发出对话内容，就是你说的话，不要有其他的背景描述。"
            response = await provider.text_chat(
                prompt=prompt,
                session_id=event.session_id,
                contexts=[]  # 确保contexts是一个空列表而不是None
            )
            yield event.plain_result(response.completion_text)
        else:
            yield event.plain_result(f"已删除{item_type}：{removed['text']}")

    @rmd.command("add")
    async def add_reminder(self, event: AstrMessageEvent, text: str, time_str: str, week: str = None, repeat: str = None, holiday_type: str = None):
        '''手动添加提醒
        
        Args:
            text(string): 提醒内容
            time_str(string): 时间，格式为 HH:MM 或 HHMM
            week(string): 可选，开始星期：mon,tue,wed,thu,fri,sat,sun
            repeat(string): 可选，重复类型：daily,weekly,monthly,yearly或带节假日类型的组合（如daily workday）
            holiday_type(string): 可选，节假日类型：workday(仅工作日执行)，holiday(仅法定节假日执行)
        '''
        try:
            # 解析时间
            try:
                datetime_str = parse_datetime(time_str)
            except ValueError as e:
                yield event.plain_result(str(e))
                return

            # 验证星期格式
            week_map = {
                'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 
                'fri': 4, 'sat': 5, 'sun': 6
            }
            
            # 改进的参数处理逻辑：尝试调整星期和重复类型参数
            if week and week.lower() not in week_map:
                # 星期格式错误，尝试将其作为repeat处理
                if week.lower() in ["daily", "weekly", "monthly", "yearly"] or week.lower() in ["workday", "holiday"]:
                    # week参数实际上可能是repeat参数
                    if repeat:
                        # 如果repeat也存在，则将week和repeat作为组合
                        holiday_type = repeat  # 将原来的repeat视为holiday_type
                        repeat = week  # 将原来的week视为repeat
                    else:
                        repeat = week  # 将原来的week视为repeat
                    week = None  # 清空week，使用默认值（今天）
                    logger.info(f"已将'{week}'识别为重复类型，默认使用今天作为开始日期")
                else:
                    yield event.plain_result("星期格式错误，可选值：mon,tue,wed,thu,fri,sat,sun")
                    return

            # 特殊处理: 检查repeat是否包含节假日类型信息
            if repeat:
                parts = repeat.split()
                if len(parts) == 2 and parts[1] in ["workday", "holiday"]:
                    # 如果repeat参数包含两部分，且第二部分是workday或holiday
                    repeat = parts[0]  # 提取重复类型
                    holiday_type = parts[1]  # 提取节假日类型

            # 验证重复类型
            repeat_types = ["daily", "weekly", "monthly", "yearly"]
            if repeat and repeat.lower() not in repeat_types:
                yield event.plain_result("重复类型错误，可选值：daily,weekly,monthly,yearly")
                return
                
            # 验证节假日类型
            holiday_types = ["workday", "holiday"]
            if holiday_type and holiday_type.lower() not in holiday_types:
                yield event.plain_result("节假日类型错误，可选值：workday(仅工作日执行)，holiday(仅法定节假日执行)")
                return

            # 获取用户ID，用于会话隔离
            creator_id = event.get_sender_id()
            
            # 获取会话ID
            raw_msg_origin = event.unified_msg_origin
            if self.unique_session:
                # 使用会话隔离
                msg_origin = self.tools.get_session_id(raw_msg_origin, creator_id)
            else:
                msg_origin = raw_msg_origin
                
            # 获取创建者昵称
            creator_name = event.message_obj.sender.nickname if hasattr(event.message_obj, 'sender') and hasattr(event.message_obj.sender, 'nickname') else None
            
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
            
            # 处理重复类型和节假日类型的组合
            final_repeat = repeat.lower() if repeat else "none"
            if repeat and holiday_type:
                final_repeat = f"{repeat.lower()}_{holiday_type.lower()}"
            
            item = {
                "text": text,
                "datetime": dt.strftime("%Y-%m-%d %H:%M"),
                "user_name": creator_id,
                "repeat": final_repeat,
                "creator_id": creator_id,
                "creator_name": creator_name,  # 添加创建者昵称
                "is_task": False  # 明确标记为提醒，不是任务
            }
            
            self.reminder_data[msg_origin].append(item)
            
            # 设置定时任务
            self.scheduler_manager.add_job(msg_origin, item, dt)
            
            await save_reminder_data(self.data_file, self.reminder_data)
            
            # 生成提示信息
            week_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
            start_str = f"从{week_names[dt.weekday()]}开始，" if week else ""
            
            # 根据重复类型和节假日类型生成文本说明
            repeat_str = "一次性"
            if repeat == "daily" and not holiday_type:
                repeat_str = "每天重复"
            elif repeat == "daily" and holiday_type == "workday":
                repeat_str = "每个工作日重复（法定节假日不触发）"
            elif repeat == "daily" and holiday_type == "holiday":
                repeat_str = "每个法定节假日重复"
            elif repeat == "weekly" and not holiday_type:
                repeat_str = "每周重复"
            elif repeat == "weekly" and holiday_type == "workday":
                repeat_str = "每周的这一天重复，但仅工作日触发"
            elif repeat == "weekly" and holiday_type == "holiday":
                repeat_str = "每周的这一天重复，但仅法定节假日触发"
            elif repeat == "monthly" and not holiday_type:
                repeat_str = "每月重复"
            elif repeat == "monthly" and holiday_type == "workday":
                repeat_str = "每月的这一天重复，但仅工作日触发"
            elif repeat == "monthly" and holiday_type == "holiday":
                repeat_str = "每月的这一天重复，但仅法定节假日触发"
            elif repeat == "yearly" and not holiday_type:
                repeat_str = "每年重复"
            elif repeat == "yearly" and holiday_type == "workday":
                repeat_str = "每年的这一天重复，但仅工作日触发"
            elif repeat == "yearly" and holiday_type == "holiday":
                repeat_str = "每年的这一天重复，但仅法定节假日触发"
            
            yield event.plain_result(f"已设置提醒:\n内容: {text}\n时间: {dt.strftime('%Y-%m-%d %H:%M')}\n{start_str}{repeat_str}\n\n使用 /rmd ls 查看所有提醒和任务")
            
        except Exception as e:
            yield event.plain_result(f"设置提醒时出错：{str(e)}")

    @rmd.command("task")
    async def add_task(self, event: AstrMessageEvent, text: str, time_str: str, week: str = None, repeat: str = None, holiday_type: str = None):
        '''手动添加任务
        
        Args:
            text(string): 任务内容
            time_str(string): 时间，格式为 HH:MM 或 HHMM
            week(string): 可选，开始星期：mon,tue,wed,thu,fri,sat,sun
            repeat(string): 可选，重复类型：daily,weekly,monthly,yearly或带节假日类型的组合（如daily workday）
            holiday_type(string): 可选，节假日类型：workday(仅工作日执行)，holiday(仅法定节假日执行)
        '''
        try:
            # 解析时间
            try:
                datetime_str = parse_datetime(time_str)
            except ValueError as e:
                yield event.plain_result(str(e))
                return

            # 验证星期格式
            week_map = {
                'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 
                'fri': 4, 'sat': 5, 'sun': 6
            }
            
            # 改进的参数处理逻辑：尝试调整星期和重复类型参数
            if week and week.lower() not in week_map:
                # 星期格式错误，尝试将其作为repeat处理
                if week.lower() in ["daily", "weekly", "monthly", "yearly"] or week.lower() in ["workday", "holiday"]:
                    # week参数实际上可能是repeat参数
                    if repeat:
                        # 如果repeat也存在，则将week和repeat作为组合
                        holiday_type = repeat  # 将原来的repeat视为holiday_type
                        repeat = week  # 将原来的week视为repeat
                    else:
                        repeat = week  # 将原来的week视为repeat
                    week = None  # 清空week，使用默认值（今天）
                    logger.info(f"已将'{week}'识别为重复类型，默认使用今天作为开始日期")
                else:
                    yield event.plain_result("星期格式错误，可选值：mon,tue,wed,thu,fri,sat,sun")
                    return

            # 特殊处理: 检查repeat是否包含节假日类型信息
            if repeat:
                parts = repeat.split()
                if len(parts) == 2 and parts[1] in ["workday", "holiday"]:
                    # 如果repeat参数包含两部分，且第二部分是workday或holiday
                    repeat = parts[0]  # 提取重复类型
                    holiday_type = parts[1]  # 提取节假日类型

            # 验证重复类型
            repeat_types = ["daily", "weekly", "monthly", "yearly"]
            if repeat and repeat.lower() not in repeat_types:
                yield event.plain_result("重复类型错误，可选值：daily,weekly,monthly,yearly")
                return
                
            # 验证节假日类型
            holiday_types = ["workday", "holiday"]
            if holiday_type and holiday_type.lower() not in holiday_types:
                yield event.plain_result("节假日类型错误，可选值：workday(仅工作日执行)，holiday(仅法定节假日执行)")
                return

            # 获取用户ID，用于会话隔离
            creator_id = event.get_sender_id()
            
            # 获取会话ID
            raw_msg_origin = event.unified_msg_origin
            if self.unique_session:
                # 使用会话隔离
                msg_origin = self.tools.get_session_id(raw_msg_origin, creator_id)
            else:
                msg_origin = raw_msg_origin
                
            # 获取创建者昵称
            creator_name = event.message_obj.sender.nickname if hasattr(event.message_obj, 'sender') and hasattr(event.message_obj.sender, 'nickname') else None
            
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
            
            # 处理重复类型和节假日类型的组合
            final_repeat = repeat.lower() if repeat else "none"
            if repeat and holiday_type:
                final_repeat = f"{repeat.lower()}_{holiday_type.lower()}"
            
            item = {
                "text": text,
                "datetime": dt.strftime("%Y-%m-%d %H:%M"),
                "user_name": "用户",  # 任务模式下不需要特别指定用户名
                "repeat": final_repeat,
                "creator_id": creator_id,
                "creator_name": creator_name,  # 添加创建者昵称
                "is_task": True  # 明确标记为任务
            }
            
            self.reminder_data[msg_origin].append(item)
            
            # 设置定时任务
            self.scheduler_manager.add_job(msg_origin, item, dt)
            
            await save_reminder_data(self.data_file, self.reminder_data)
            
            # 生成提示信息
            week_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
            start_str = f"从{week_names[dt.weekday()]}开始，" if week else ""
            
            # 根据重复类型和节假日类型生成文本说明
            repeat_str = "一次性"
            if repeat == "daily" and not holiday_type:
                repeat_str = "每天重复"
            elif repeat == "daily" and holiday_type == "workday":
                repeat_str = "每个工作日重复（法定节假日不触发）"
            elif repeat == "daily" and holiday_type == "holiday":
                repeat_str = "每个法定节假日重复"
            elif repeat == "weekly" and not holiday_type:
                repeat_str = "每周重复"
            elif repeat == "weekly" and holiday_type == "workday":
                repeat_str = "每周的这一天重复，但仅工作日触发"
            elif repeat == "weekly" and holiday_type == "holiday":
                repeat_str = "每周的这一天重复，但仅法定节假日触发"
            elif repeat == "monthly" and not holiday_type:
                repeat_str = "每月重复"
            elif repeat == "monthly" and holiday_type == "workday":
                repeat_str = "每月的这一天重复，但仅工作日触发"
            elif repeat == "monthly" and holiday_type == "holiday":
                repeat_str = "每月的这一天重复，但仅法定节假日触发"
            elif repeat == "yearly" and not holiday_type:
                repeat_str = "每年重复"
            elif repeat == "yearly" and holiday_type == "workday":
                repeat_str = "每年的这一天重复，但仅工作日触发"
            elif repeat == "yearly" and holiday_type == "holiday":
                repeat_str = "每年的这一天重复，但仅法定节假日触发"
            
            yield event.plain_result(f"已设置任务:\n内容: {text}\n时间: {dt.strftime('%Y-%m-%d %H:%M')}\n{start_str}{repeat_str}\n\n使用 /rmd ls 查看所有提醒和任务")
            
        except Exception as e:
            yield event.plain_result(f"设置任务时出错：{str(e)}")

    @rmd.command("help")
    async def show_help(self, event: AstrMessageEvent):
        '''显示帮助信息'''
        help_text = """提醒与任务功能指令说明：

【提醒】：到时间后会提醒你做某事
【任务】：到时间后AI会自动执行指定的操作

1. 添加提醒：
   /rmd add <内容> <时间> [开始星期] [重复类型] [--holiday_type=...]
   例如：
   - /rmd add 写周报 8:05
   - /rmd add 吃饭 8:05 sun daily (从周日开始每天)
   - /rmd add 开会 8:05 mon weekly (每周一)
   - /rmd add 交房租 8:05 fri monthly (从周五开始每月)
   - /rmd add 上班打卡 8:30 daily workday (每个工作日，法定节假日不触发)
   - /rmd add 休息提醒 9:00 daily holiday (每个法定节假日触发)

2. 添加任务：
   /rmd task <内容> <时间> [开始星期] [重复类型] [--holiday_type=...]
   例如：
   - /rmd task 发送天气预报 8:00
   - /rmd task 汇总今日新闻 18:00 daily
   - /rmd task 推送工作安排 9:00 mon weekly workday (每周一工作日推送)

3. 查看提醒和任务：
   /rmd ls - 列出所有提醒和任务

4. 删除提醒或任务：
   /rmd rm <序号> - 删除指定提醒或任务，注意任务序号是提醒序号继承，比如提醒有两个，任务1的序号就是3（llm会自动重编号）

5. 星期可选值：
   - mon: 周一
   - tue: 周二
   - wed: 周三
   - thu: 周四
   - fri: 周五
   - sat: 周六
   - sun: 周日

6. 重复类型：
   - daily: 每天重复
   - weekly: 每周重复
   - monthly: 每月重复
   - yearly: 每年重复

7. 节假日类型：
   - workday: 仅工作日触发（法定节假日不触发）
   - holiday: 仅法定节假日触发

8. AI智能提醒与任务
   正常对话即可，AI会自己设置提醒或任务，但需要AI支持LLM

9. 会话隔离功能
   {session_isolation_status}
   - 关闭状态：群聊中所有成员共享同一组提醒和任务
   - 开启状态：群聊中每个成员都有自己独立的提醒和任务
   
   可以通过管理面板的插件配置开启或关闭此功能

注：时间格式为 HH:MM 或 HHMM，如 8:05 或 0805
法定节假日数据来源：http://timor.tech/api/holiday""".format(
           session_isolation_status="当前已开启会话隔离" if self.unique_session else "当前未开启会话隔离"
        )
        yield event.plain_result(help_text)