import datetime
import json
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
        
        # 创建猴子补丁用于MessageSesion.from_str
        # 这会临时修改方法以适应任何格式的session_id字符串
        try:
            from astrbot.core.platform.astr_message_event import MessageSesion
            original_from_str = MessageSesion.from_str
            
            @classmethod
            def safe_from_str(cls, session_str):
                try:
                    # 先尝试原始方法
                    return original_from_str(session_str)
                except Exception as e:
                    # 如果正常解析失败，创建一个默认的MessageSesion
                    logger.warning(f"安全解析session失败：{str(e)}，使用安全模式")
                    
                    # 特殊处理含多个冒号的情况
                    if session_str.count(":") >= 2:
                        parts = session_str.split(":", 2)
                        platform = parts[0]
                        
                        # 智能判断消息类型
                        if "FriendMessage" in session_str:
                            message_type = "FriendMessage"
                        elif "GroupMessage" in session_str:
                            message_type = "GroupMessage"
                        else:
                            message_type = parts[1] if len(parts) > 1 else "FriendMessage"
                            
                        session_id = parts[2] if len(parts) > 2 else "unknown"
                    else:
                        # 处理简单情况
                        parts = session_str.split(":", 1)
                        platform = parts[0] if parts else "unknown"
                        message_type = "FriendMessage"  # 默认为私聊
                        session_id = parts[1] if len(parts) > 1 else session_str
                    
                    # 尝试创建MessageSesion对象
                    try:
                        return cls(platform, message_type, session_id)
                    except Exception as inner_e:
                        logger.error(f"创建安全MessageSesion失败: {str(inner_e)}")
                        # 如果还是失败，返回一个硬编码的对象
                        return cls("unknown", "FriendMessage", "unknown")
            
            # 应用猴子补丁
            if hasattr(MessageSesion, "from_str"):
                MessageSesion.from_str = safe_from_str
                logger.info("已应用MessageSesion安全解析补丁")
            
        except Exception as e:
            logger.error(f"设置安全解析器失败: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
        
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
                    # 检查对话上下文
                    conversation = None
                    contexts = []
                    
                    # 获取用户当前与LLM的对话以获得上下文信息
                    curr_cid = await self.context.conversation_manager.get_curr_conversation_id(unified_msg_origin)
                    
                    if curr_cid:
                        conversation = await self.context.conversation_manager.get_conversation(unified_msg_origin, curr_cid)
                        if conversation:
                            contexts = json.loads(conversation.history)
                            logger.info(f"找到用户对话，对话ID: {curr_cid}, 上下文长度: {len(contexts)}")
                    
                    # 如果没有对话或需要新建对话
                    if not curr_cid or not conversation:
                        curr_cid = await self.context.conversation_manager.new_conversation(unified_msg_origin)
                        conversation = await self.context.conversation_manager.get_conversation(unified_msg_origin, curr_cid)
                        logger.info(f"创建新对话，对话ID: {curr_cid}")
                    
                    # 检查是否是调用LLM函数的任务
                    if task_text.startswith("请调用") and "函数" in task_text:
                        # 这是一个请求调用LLM函数的任务
                        # 我们需要直接告诉AI执行这个任务，而不是作为普通消息处理
                        prompt = f"用户请求你执行以下操作：{task_text}。请直接执行这个任务，不要解释你在做什么，就像用户刚刚发出这个请求一样。"
                    else:
                        # 普通任务，直接让AI执行
                        prompt = f"请执行以下任务：{task_text}。请直接执行，不要提及这是一个预设任务。"
                    
                    logger.info(f"发送提示词到LLM: {prompt[:50]}...")
                    
                    # 添加系统提示词，确保LLM知道它可以调用函数
                    system_prompt = "你可以调用各种函数来帮助用户完成任务，如获取天气、设置提醒等。请根据用户的需求直接调用相应的函数。"
                    
                    # 使用方法1: 直接调用LLM，获取响应后手动处理
                    # 这种方式可以让我们更精细地控制LLM调用过程和函数执行
                    response = await provider.text_chat(
                        prompt=prompt,
                        session_id=unified_msg_origin,
                        contexts=contexts,  # 使用用户现有的对话上下文
                        func_tool=func_tool,  # 添加函数工具管理器，让AI可以调用LLM函数
                        system_prompt=system_prompt  # 添加系统提示词
                    )
                    
                    logger.info(f"LLM响应类型: {response.role}")
                    
                    # 记录用户操作到历史，先添加用户的提问到历史记录
                    new_contexts = contexts.copy()
                    new_contexts.append({"role": "user", "content": task_text})
                    
                    # 标记是否需要发送结果给用户
                    need_send_result = True
                    result_msg = MessageChain()
                    
                    # 检查是否有工具调用
                    if response.role == "tool" and hasattr(response, 'tools_call_name') and response.tools_call_name:
                        logger.info(f"检测到工具调用: {response.tools_call_name}")
                        
                        # 收集工具调用结果
                        tool_results = []
                        has_sent_messages = []  # 记录哪些函数已经自己发送了消息
                        
                        for i, func_name in enumerate(response.tools_call_name):
                            func_args = response.tools_call_args[i] if i < len(response.tools_call_args) else {}
                            func_id = response.tools_call_ids[i] if i < len(response.tools_call_ids) else "unknown"
                            
                            logger.info(f"执行工具调用: {func_name}({func_args})")
                            
                            try:
                                # 获取函数对象和处理器
                                func_obj = func_tool.get_func(func_name)
                                
                                if func_obj and func_obj.handler:
                                    # 创建最小的事件对象来调用函数
                                    # 导入必要的类
                                    from astrbot.api.platform import AstrBotMessage, PlatformMetadata, MessageType, MessageMember
                                    from astrbot.core.platform.astr_message_event import AstrMessageEvent
                                    
                                    # 创建基本消息对象
                                    msg = AstrBotMessage()
                                    msg.message_str = task_text
                                    msg.session_id = unified_msg_origin
                                    msg.type = MessageType.FRIEND_MESSAGE if is_private_chat else MessageType.GROUP_MESSAGE
                                    
                                    # 如果有创建者ID，则设置发送者信息
                                    if "creator_id" in reminder:
                                        msg.sender = MessageMember(reminder["creator_id"], reminder.get("creator_name", "用户"))
                                    else:
                                        msg.sender = MessageMember("unknown", "用户")
                                        
                                    # 不再尝试分割session_id，而是直接使用消息来源标识平台
                                    platform_name = "unknown"
                                    if unified_msg_origin.startswith("gewechat"):
                                        platform_name = "gewechat"
                                    elif unified_msg_origin.startswith("aiocqhttp"):
                                        platform_name = "aiocqhttp"
                                    elif unified_msg_origin.startswith("ntchat"):
                                        platform_name = "ntchat"
                                    elif ":" in unified_msg_origin:
                                        # 如果有冒号，尝试获取第一段作为平台名
                                        platform_name = unified_msg_origin.split(":", 1)[0]

                                    # 创建一个特殊的session_id用于发送功能
                                    send_session_id = None
                                    if ":" in unified_msg_origin:
                                        if len(unified_msg_origin.split(":")) >= 3:
                                            # 保留原始session_id结构，但确保不会因分割过多引发错误
                                            parts = unified_msg_origin.split(":", 2)
                                            msg_type = "FriendMessage" if is_private_chat else "GroupMessage"
                                            send_session_id = f"{parts[0]}:{msg_type}:{parts[2]}"
                                        else:
                                            # 使用原始session_id
                                            send_session_id = unified_msg_origin
                                    else:
                                        # 如果session_id没有合适格式，构造一个基本形式
                                        msg_type = "FriendMessage" if is_private_chat else "GroupMessage"
                                        send_session_id = f"{platform_name}:{msg_type}:unknown"
                                    
                                    # 创建事件对象
                                    meta = PlatformMetadata(platform_name, "scheduler")
                                    event = AstrMessageEvent(
                                        message_str=task_text,
                                        message_obj=msg,
                                        platform_meta=meta,
                                        session_id=unified_msg_origin
                                    )
                                    
                                    # 添加特殊属性，供函数调用时使用
                                    event._send_session_id = send_session_id
                                    event._has_send_oper = False
                                    
                                    # 为发送消息提供一个特殊工具方法
                                    # 一些函数可能会直接调用event.message_obj.platform.send_message
                                    # 所以我们需要确保这个方法可用
                                    class PlatformHelperWithSend:
                                        def __init__(self, context, session_id):
                                            self.context = context
                                            self.session_id = session_id
                                            
                                        async def send_message(self, message):
                                            event._has_send_oper = True
                                            try:
                                                return await self.context.send_message(self.session_id, message)
                                            except Exception as e:
                                                logger.error(f"平台工具发送消息失败: {str(e)}")
                                                return False
                                    
                                    # 添加平台辅助工具到消息对象
                                    if not hasattr(event.message_obj, "platform"):
                                        event.message_obj.platform = PlatformHelperWithSend(self.context, send_session_id)
                                    
                                    # 添加其他常用属性和方法，确保各种函数能正常调用
                                    def ensure_attributes(event_obj):
                                        """确保事件对象具有所有可能需要的属性"""
                                        # 添加常用的reply方法
                                        if not hasattr(event_obj, "reply"):
                                            async def reply_func(content):
                                                event_obj._has_send_oper = True
                                                msg_chain = MessageChain()
                                                if isinstance(content, str):
                                                    msg_chain.chain.append(Plain(content))
                                                else:
                                                    msg_chain = content
                                                return await self.context.send_message(send_session_id, msg_chain)
                                            event_obj.reply = reply_func
                                        
                                        # 添加session_id属性
                                        if not hasattr(event_obj, "session_id"):
                                            event_obj.session_id = send_session_id
                                        
                                        # 添加get_session_id方法
                                        if not hasattr(event_obj, "get_session_id"):
                                            event_obj.get_session_id = lambda: send_session_id
                                        
                                        # 添加get_platform_type方法
                                        if not hasattr(event_obj, "get_platform_type"):
                                            event_obj.get_platform_type = lambda: platform_name
                                        
                                        # 添加get_message_type方法
                                        if not hasattr(event_obj, "get_message_type"):
                                            msg_type = "friend" if is_private_chat else "group"
                                            event_obj.get_message_type = lambda: msg_type
                                        
                                        # 添加get_sender_id方法（如果还没有）
                                        if hasattr(event_obj, "get_sender_id"):
                                            original_get_sender = event_obj.get_sender_id
                                            def safe_get_sender():
                                                try:
                                                    return original_get_sender()
                                                except:
                                                    return reminder.get("creator_id", "unknown")
                                            event_obj.get_sender_id = safe_get_sender
                                        else:
                                            event_obj.get_sender_id = lambda: reminder.get("creator_id", "unknown")
                                    
                                    # 应用属性保证
                                    ensure_attributes(event)
                                    
                                    # 调用函数
                                    try:
                                        # 记录调用前的状态
                                        has_sent_message_before = event._has_send_oper
                                        
                                        # 调用函数
                                        func_result = await func_obj.handler(event, **func_args)
                                        logger.info(f"函数调用结果: {func_result}")
                                        
                                        # 检查函数是否已经自己发送了消息
                                        if event._has_send_oper and not has_sent_message_before:
                                            logger.info(f"函数 {func_name} 已自行发送消息，不需要我们再发送")
                                            has_sent_messages.append(func_name)
                                        
                                        # 只有当函数返回值不为None且没有自行发送消息时，才添加到工具结果列表
                                        if func_result is not None and func_name not in has_sent_messages:
                                            tool_results.append({
                                                "name": func_name,
                                                "result": func_result
                                            })
                                    except Exception as e:
                                        logger.error(f"执行函数时出错: {str(e)}")
                                        if func_name not in has_sent_messages:
                                            tool_results.append({
                                                "name": func_name,
                                                "result": f"错误: {str(e)}"
                                            })
                                else:
                                    logger.warning(f"找不到函数处理器: {func_name}")
                            except Exception as e:
                                logger.error(f"准备执行函数调用时出错: {str(e)}")
                                import traceback
                                logger.error(traceback.format_exc())
                        
                        # 函数处理逻辑结束后判断是否需要发送结果
                        # 如果所有函数都已经自己发送了消息，我们就不需要再发送了
                        if len(has_sent_messages) == len(response.tools_call_name):
                            logger.info("所有函数都已自行发送消息，不需要额外发送结果")
                            need_send_result = False
                        # 如果只有部分函数自己发送了消息，我们只润色没有自己发送消息的函数的结果
                        elif tool_results:
                            # 如果有函数调用结果，让LLM润色结果
                            # 构建提示词，让LLM基于工具调用结果生成自然语言响应
                            tool_results_text = ""
                            for tr in tool_results:
                                tool_results_text += f"- {tr['name']}: {tr['result']}\n"
                            
                            summary_prompt = f"""我执行了用户的任务"{task_text}"，并获得了以下结果：
                            
{tool_results_text}

请对这些结果进行整理和润色，用自然、友好的语言向用户展示这些信息。直接回复用户的问题，不要提及这是定时任务或使用了什么函数。"""
                            
                            # 使用LLM润色结果，不使用函数调用
                            summary_response = await provider.text_chat(
                                prompt=summary_prompt,
                                session_id=unified_msg_origin,
                                contexts=[]  # 不使用上下文，避免混淆
                            )
                            
                            if summary_response and summary_response.completion_text:
                                result_msg.chain.append(Plain(summary_response.completion_text))
                                # 添加AI的回复到历史记录
                                new_contexts.append({"role": "assistant", "content": summary_response.completion_text})
                            else:
                                # 如果润色失败，直接显示原始结果
                                result_text = "执行结果:\n"
                                for tr in tool_results:
                                    result_text += f"[{tr['name']}]: {tr['result']}\n"
                                result_msg.chain.append(Plain(result_text))
                                # 添加结果到历史记录
                                new_contexts.append({"role": "assistant", "content": result_text})
                        else:
                            # 没有工具调用结果
                            if has_sent_messages:
                                # 如果有函数自己发送了消息，我们不需要再发送额外的消息
                                need_send_result = False
                            else:
                                result_msg.chain.append(Plain("任务执行完成，但未能获取有效结果。"))
                                # 添加结果到历史记录
                                new_contexts.append({"role": "assistant", "content": "任务执行完成，但未能获取有效结果。"})
                    elif response.role == "assistant" and response.completion_text:
                        # 如果只有文本回复，构建普通消息
                        result_msg.chain.append(Plain(response.completion_text))
                        # 添加AI的回复到历史记录
                        new_contexts.append({"role": "assistant", "content": response.completion_text})
                    else:
                        # 没有文本回复也没有工具调用，返回默认消息
                        result_msg.chain.append(Plain("任务执行完成，但未返回结果。"))
                        # 添加结果到历史记录
                        new_contexts.append({"role": "assistant", "content": "任务执行完成，但未返回结果。"})
                    
                    # 只有在需要时才发送消息
                    if need_send_result:
                        logger.info(f"尝试发送消息到: {unified_msg_origin}")
                        send_result = await self.context.send_message(unified_msg_origin, result_msg)
                        logger.info(f"消息发送结果: {send_result}")
                    else:
                        logger.info("跳过发送结果，因为函数已自行处理消息发送")
                    
                    # 更新对话历史
                    if conversation:
                        await self.context.conversation_manager.update_conversation(
                            unified_msg_origin, 
                            curr_cid, 
                            history=new_contexts
                        )
                        logger.info(f"已更新对话历史，对话ID: {curr_cid}")
                    
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