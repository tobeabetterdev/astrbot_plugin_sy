from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import *
from astrbot.api.event.filter import command, command_group
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from astrbot.api import logger
import datetime
import json
import os
from typing import Union

@register("ai_reminder", "kjqwdw", "智能定时任务", "1.0.0")
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
            for reminder in self.reminder_data[group]:
                if "datetime" not in reminder:
                    continue
                
                if reminder.get("repeat", "none") == "none" and self._is_outdated(reminder):
                    continue
                
                dt = datetime.datetime.strptime(reminder["datetime"], "%Y-%m-%d %H:%M")
                
                # 根据重复类型设置不同的触发器
                if reminder.get("repeat") == "daily":
                    self.scheduler.add_job(
                        self._reminder_callback,
                        'cron',
                        args=[group, reminder],
                        hour=dt.hour,
                        minute=dt.minute,
                        misfire_grace_time=60
                    )
                elif reminder.get("repeat") == "weekly":
                    self.scheduler.add_job(
                        self._reminder_callback,
                        'cron',
                        args=[group, reminder],
                        day_of_week=dt.weekday(),
                        hour=dt.hour,
                        minute=dt.minute,
                        misfire_grace_time=60
                    )
                elif reminder.get("repeat") == "monthly":
                    self.scheduler.add_job(
                        self._reminder_callback,
                        'cron',
                        args=[group, reminder],
                        day=dt.day,
                        hour=dt.hour,
                        minute=dt.minute,
                        misfire_grace_time=60
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
                        misfire_grace_time=60
                    )
                else:
                    self.scheduler.add_job(
                        self._reminder_callback,
                        'date',
                        args=[group, reminder],
                        run_date=dt,
                        misfire_grace_time=60
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
            else:
                msg_origin = event.unified_msg_origin
            
            if msg_origin not in self.reminder_data:
                self.reminder_data[msg_origin] = []
            
            reminder = {
                "text": text,
                "datetime": datetime_str,
                "user_name": user_name,
                "repeat": repeat or "none"
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
                    misfire_grace_time=60
                )
            elif repeat == "weekly":
                self.scheduler.add_job(
                    self._reminder_callback,
                    'cron',
                    args=[msg_origin, reminder],
                    day_of_week=dt.weekday(),
                    hour=dt.hour,
                    minute=dt.minute,
                    misfire_grace_time=60
                )
            elif repeat == "monthly":
                self.scheduler.add_job(
                    self._reminder_callback,
                    'cron',
                    args=[msg_origin, reminder],
                    day=dt.day,
                    hour=dt.hour,
                    minute=dt.minute,
                    misfire_grace_time=60
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
                    misfire_grace_time=60
                )
            else:
                self.scheduler.add_job(
                    self._reminder_callback,
                    'date',
                    args=[msg_origin, reminder],
                    run_date=dt,
                    misfire_grace_time=60
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
            # 使用LLM生成更自然的提醒消息
            prompt = f"你现在在和{reminder['user_name']}对话，发出提醒给他，提醒内容是'{reminder['text']}'，如果提醒内容是要求你做事，比如讲故事，你就执行。直接发出对话内容，就是你说的话，不要有其他的背景描述。"
            response = await provider.text_chat(
                prompt=prompt,
                session_id=unified_msg_origin
            )
            logger.info(f"Reminder Activated: {reminder['text']}, created by {unified_msg_origin}")
            await self.context.send_message(unified_msg_origin, MessageEventResult().message("[提醒]"+response.completion_text))
        else:
            await self.context.send_message(unified_msg_origin, MessageEventResult().message(f"提醒: {reminder['text']}"))

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
            reminder_list = "\n".join([f"- {r['text']} (时间: {r['datetime']})" for r in reminders])
            prompt = f"请帮我整理并展示以下任务列表，用自然的语言表达：\n{reminder_list}\n同时告诉用户可以使用/rmd rm <序号>来删除提醒。直接发出对话内容，就是你说的话，不要有其他的背景描述。"
            response = await provider.text_chat(
                prompt=prompt,
                session_id=event.session_id
            )
            yield event.plain_result(response.completion_text)
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



