from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import *
from astrbot.api.event.filter import command, command_group
from astrbot.api import logger, AstrBotConfig
import os
from .utils import load_reminder_data
from .scheduler import ReminderScheduler
from .tools import ReminderTools
from .commands import ReminderCommands

@register("ai_reminder", "kjqwdw", "智能定时任务，输入/rmd help查看帮助", "1.1.3")
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
        
        # 初始化命令
        self.commands = ReminderCommands(self)
        
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
        async for result in self.commands.list_reminders(event):
            yield result

    @rmd.command("rm")
    async def remove_reminder(self, event: AstrMessageEvent, index: int):
        '''删除提醒或任务
        
        Args:
            index(int): 提醒或任务的序号
        '''
        async for result in self.commands.remove_reminder(event, index):
            yield result

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
        async for result in self.commands.add_reminder(event, text, time_str, week, repeat, holiday_type):
            yield result

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
        async for result in self.commands.add_task(event, text, time_str, week, repeat, holiday_type):
            yield result

    @rmd.command("help")
    async def show_help(self, event: AstrMessageEvent):
        '''显示帮助信息'''
        async for result in self.commands.show_help(event):
            yield result