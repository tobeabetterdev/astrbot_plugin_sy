from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import *
from astrbot.api.event.filter import command, command_group
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from astrbot.api import logger
from astrbot.api.event import MessageChain
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
            # 构建提醒消息
            prompt = f"你现在在和{reminder['user_name']}对话，发出提醒给他，提醒内容是'{reminder['text']}'，如果提醒内容是要求你做事，比如讲故事，你就执行。直接发出对话内容，就是你说的话，不要有其他的背景描述。"
            response = await provider.text_chat(
                prompt=prompt,
                session_id=unified_msg_origin
            )
            logger.info(f"Reminder Activated: {reminder['text']}, created by {unified_msg_origin}")
            
            # 构建消息链
            msg = MessageChain()
            
            # 如果是群聊且存在创建者ID，则添加@
            if "creator_id" in reminder and reminder["creator_id"]:
                msg.chain.append(At(qq=reminder["creator_id"]))
                msg.chain.append(Plain(" "))  # 添加空格分隔
            
            msg.chain.append(Plain("[提醒]" + response.completion_text))
            
            await self.context.send_message(unified_msg_origin, msg)
        else:
            # 构建基础消息链
            msg = MessageChain()
            
            # 如果是群聊且存在创建者ID，则添加@
            if "creator_id" in reminder and reminder["creator_id"]:
                msg.chain.append(At(qq=reminder["creator_id"]))
                msg.chain.append(Plain(" "))  # 添加空格分隔
            
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

    @rmd.command("add")
    async def add_reminder(self, event: AstrMessageEvent, text: str, datetime_str: str, repeat: str = None):
        '''手动添加提醒
        
        Args:
            text(string): 提醒内容
            datetime_str(string): 提醒时间，格式为 %Y-%m-%d %H:%M
            repeat(string): 可选，重复类型：daily(每天)，weekly(每周)，monthly(每月)，yearly(每年)
        '''
        try:
            # 验证时间格式
            try:
                datetime.datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
            except ValueError:
                yield event.plain_result("时间格式错误，请使用 YYYY-MM-DD HH:MM 格式")
                return

            # 验证重复类型
            if repeat and repeat not in ["daily", "weekly", "monthly", "yearly"]:
                yield event.plain_result("重复类型错误，可选值：daily(每天)，weekly(每周)，monthly(每月)，yearly(每年)")
                return

            msg_origin = event.unified_msg_origin
            creator_id = event.get_sender_id()
            
            if msg_origin not in self.reminder_data:
                self.reminder_data[msg_origin] = []
            
            reminder = {
                "text": text,
                "datetime": datetime_str,
                "user_name": creator_id,  # 对象就是创建者自己
                "repeat": repeat or "none",
                "creator_id": creator_id
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
            
            yield event.plain_result(f"已设置提醒:\n内容: {text}\n时间: {datetime_str}{repeat_str}\n\n使用 /rmd ls 查看所有提醒")
            
        except Exception as e:
            yield event.plain_result(f"设置提醒时出错：{str(e)}")

    @rmd.command("help")
    async def show_help(self, event: AstrMessageEvent):
        '''显示帮助信息'''
        help_text = """提醒功能指令说明：
1. 手动添加提醒：
   /rmd add <内容> <时间> [重复类型]
   例如：
   - /rmd add 写周报 2024-01-20 18:00
   - /rmd add 喝水 2024-01-20 14:00 daily

2. ai智能提醒:
   直接和ai对话即可，ai会自动解析你的对话内容，并设置提醒，需要ai支持llm函数。

3. 查看提醒：
   /rmd ls - 列出所有提醒

4. 删除提醒：
   /rmd rm <序号> - 删除指定提醒

5. 重复类型可选值：
   - daily: 每天重复
   - weekly: 每周重复
   - monthly: 每月重复
   - yearly: 每年重复
   - 不填则不重复

注：时间格式为 YYYY-MM-DD HH:MM"""
        yield event.plain_result(help_text)



