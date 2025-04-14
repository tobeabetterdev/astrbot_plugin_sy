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
        
        logger.info(f"开始执行{'任务' if is_task else '提醒'}: {reminder['text']} 在 {unified_msg_origin}")
        
        if provider:
            logger.info(f"使用提供商: {provider.meta().type}")
            if is_task:
                # 任务模式：模拟用户发送消息，让AI执行任务
                task_text = reminder['text']
                logger.info(f"Task Activated: {task_text}, attempting to execute for {unified_msg_origin}")
                
                # 获取LLM工具管理器供AI使用
                func_tool = self.context.get_llm_tool_manager()
                logger.info(f"LLM工具管理器加载成功: {func_tool is not None}")
                
                try:
                    # 检查是否是调用LLM函数的任务
                    if task_text.startswith("请调用") and "函数" in task_text:
                        # 这是一个请求调用LLM函数的任务
                        # 我们需要直接告诉AI执行这个任务，而不是作为普通消息处理
                        prompt = f"用户请求你执行以下操作：{task_text}。请直接执行这个任务，不要解释你在做什么，就像用户刚刚发出这个请求一样。"
                    else:
                        # 普通任务，直接让AI执行
                        prompt = f"请执行以下任务：{task_text}。这是用户之前设置的定时任务，现在需要你执行。请直接执行，不要提及这是一个预设任务。"
                    
                    logger.info(f"发送提示词到LLM: {prompt[:50]}...")
                    
                    # 添加系统提示词，确保LLM知道它可以调用函数
                    system_prompt = "你可以调用各种函数来帮助用户完成任务，如获取天气、设置提醒等。请根据用户的需求直接调用相应的函数。"
                    
                    response = await provider.text_chat(
                        prompt=prompt,
                        session_id=unified_msg_origin,
                        contexts=[],
                        func_tool=func_tool,  # 添加函数工具管理器，让AI可以调用LLM函数
                        system_prompt=system_prompt  # 添加系统提示词
                    )
                    
                    logger.info(f"LLM响应: {response}")
                    logger.info(f"收到LLM响应: {'成功' if response else '失败'}")
                    if response:
                        logger.info(f"响应内容长度: {len(response.completion_text) if response.completion_text else 0}")
                        logger.info(f"响应工具调用: {len(response.tools_call_name) if hasattr(response, 'tools_call_name') and response.tools_call_name else 0}")
                    
                    # 检查是否有工具调用
                    if hasattr(response, 'tools_call_name') and response.tools_call_name:
                        logger.info(f"检测到工具调用: {response.tools_call_name}")
                        
                        # 这次我们使用两阶段调用
                        # 第一阶段：收集所有工具调用结果
                        tool_results = []
                        
                        for i, func_name in enumerate(response.tools_call_name):
                            func_args = response.tools_call_args[i] if i < len(response.tools_call_args) else {}
                            func_id = response.tools_call_ids[i] if i < len(response.tools_call_ids) else "unknown"
                            
                            logger.info(f"执行工具调用: {func_name}({func_args})")
                            
                            try:
                                # 直接使用框架提供的函数调用机制
                                # 获取handler
                                handler = None
                                from astrbot.core.star.star_handler import star_handlers_registry, EventType
                                handlers = star_handlers_registry.get_handlers_by_event_type(EventType.OnCallingFuncToolEvent)
                                for h in handlers:
                                    if h.handler_name == func_name:
                                        handler = h.handler
                                        break
                                
                                if handler:
                                    # 创建最小的事件对象来调用函数
                                    # 导入必要的类
                                    from astrbot.api.platform import AstrBotMessage, PlatformMetadata, MessageType, MessageMember
                                    from astrbot.core.platform.astr_message_event import AstrMessageEvent
                                    
                                    # 创建消息对象
                                    msg = AstrBotMessage()
                                    msg.message_str = task_text
                                    msg.session_id = unified_msg_origin
                                    msg.type = MessageType.FRIEND_MESSAGE if is_private_chat else MessageType.GROUP_MESSAGE
                                    if "creator_id" in reminder:
                                        msg.sender = MessageMember(reminder["creator_id"], reminder.get("creator_name", "用户"))
                                    else:
                                        msg.sender = MessageMember("unknown", "用户")
                                        
                                    # 创建事件对象
                                    platform_name = unified_msg_origin.split(":")[0]
                                    meta = PlatformMetadata(platform_name, "scheduler")
                                    event = AstrMessageEvent(
                                        message_str=task_text,
                                        message_obj=msg,
                                        platform_meta=meta,
                                        session_id=unified_msg_origin
                                    )
                                    
                                    # 调用函数
                                    func_result = await handler(event, **func_args)
                                    logger.info(f"函数调用结果: {func_result}")
                                    
                                    # 添加到工具结果列表
                                    if func_result:
                                        tool_results.append({
                                            "name": func_name,
                                            "result": func_result
                                        })
                                else:
                                    logger.warning(f"找不到函数处理器: {func_name}")
                            except Exception as e:
                                logger.error(f"执行函数调用时出错: {str(e)}")
                                import traceback
                                logger.error(traceback.format_exc())
                                
                        # 第二阶段：让LLM润色结果
                        if tool_results:
                            # 构建提示词，让LLM基于工具调用结果生成自然语言响应
                            tool_results_text = ""
                            for tr in tool_results:
                                tool_results_text += f"- {tr['name']}: {tr['result']}\n"
                            
                            summary_prompt = f"""我执行了用户的任务"{task_text}"，并获得了以下结果：
                            
{tool_results_text}

请对这些结果进行整理和润色，用自然、友好的语言向用户展示这些信息。不要提及这是一个定时任务，直接回复用户的问题。"""
                            
                            # 使用LLM润色结果
                            summary_response = await provider.text_chat(
                                prompt=summary_prompt,
                                session_id=unified_msg_origin,
                                contexts=[]
                            )
                            
                            # 构建结果消息
                            result_msg = MessageChain()
                            if summary_response and summary_response.completion_text:
                                result_msg.chain.append(Plain(summary_response.completion_text))
                            else:
                                # 如果润色失败，直接显示原始结果
                                result_text = "执行结果：\n"
                                for tr in tool_results:
                                    result_text += f"[{tr['name']}]: {tr['result']}\n"
                                result_msg.chain.append(Plain(result_text))
                        else:
                            # 没有工具调用结果
                            result_msg = MessageChain()
                            result_msg.chain.append(Plain("任务执行完成，但未能获取有效结果。"))
                    elif response and response.completion_text:
                        # 如果只有文本回复，构建普通消息
                        result_msg = MessageChain()
                        result_msg.chain.append(Plain(response.completion_text))
                    else:
                        # 没有文本回复也没有工具调用，返回默认消息
                        result_msg = MessageChain()
                        result_msg.chain.append(Plain("任务执行完成，但未返回结果。"))
                    
                    logger.info(f"尝试发送消息到: {unified_msg_origin}")
                    send_result = await self.context.send_message(unified_msg_origin, result_msg)
                    logger.info(f"消息发送结果: {send_result}")
                    
                    logger.info(f"Task executed: {task_text}")
                except Exception as e:
                    logger.error(f"执行任务时出错: {str(e)}")
                    import traceback
                    logger.error(traceback.format_exc())
                    
                    # 尝试发送错误消息
                    error_msg = MessageChain()
                    error_msg.chain.append(Plain(f"执行任务时出错: {str(e)}"))
                    await self.context.send_message(unified_msg_origin, error_msg)
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
                
                send_result = await self.context.send_message(unified_msg_origin, msg)
                logger.info(f"消息发送结果: {send_result}")
        else:
            logger.warning(f"没有可用的提供商，使用简单消息")
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
            
            send_result = await self.context.send_message(unified_msg_origin, msg)
            logger.info(f"消息发送结果: {send_result}")
            
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