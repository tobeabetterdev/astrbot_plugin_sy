import datetime
import json
import random
from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.message_components import At, Plain
from astrbot.api.platform import AstrBotMessage, PlatformMetadata, MessageType, MessageMember
from astrbot.core.platform.astr_message_event import AstrMessageEvent, MessageSesion
from .utils import filter_thinking_content


class ReminderMessageHandler:
    """处理提醒消息的发送和格式化"""
    
    def __init__(self, context, wechat_platforms):
        self.context = context
        self.wechat_platforms = wechat_platforms
    
    def is_private_chat(self, unified_msg_origin: str) -> bool:
        """判断是否为私聊"""
        return ":FriendMessage:" in unified_msg_origin
    
    def is_group_chat(self, unified_msg_origin: str) -> bool:
        """判断是否为群聊"""
        return (":GroupMessage:" in unified_msg_origin) or ("@chatroom" in unified_msg_origin)
    
    def get_original_session_id(self, session_id: str) -> str:
        """从隔离格式的会话ID中提取原始会话ID，用于消息发送"""
        # 检查是否是微信平台
        is_wechat_platform = any(session_id.startswith(platform) for platform in self.wechat_platforms)
        
        # 处理微信群聊的特殊情况
        if "@chatroom" in session_id:
            # 微信群聊ID可能有两种格式:
            # 1. platform:GroupMessage:12345678@chatroom_wxid_abc123 (带用户隔离)
            # 2. platform:GroupMessage:12345678@chatroom (原始格式)
            
            # 提取平台前缀
            platform_prefix = ""
            if ":" in session_id:
                parts = session_id.split(":", 2)
                if len(parts) >= 2:
                    platform_prefix = f"{parts[0]}:{parts[1]}:"
            
            # 然后处理@chatroom后面的部分
            chatroom_parts = session_id.split("@chatroom")
            if len(chatroom_parts) == 2:
                if chatroom_parts[1].startswith("_"):
                    # 如果有下划线，说明这是带用户隔离的格式
                    room_id = chatroom_parts[0].split(":")[-1]
                    return f"{platform_prefix}{room_id}@chatroom"
                else:
                    # 这已经是原始格式，直接返回
                    return session_id
        
        # 处理其他平台的情况
        if "_" in session_id and ":" in session_id:
            # 首先判断是否是微信相关平台
            if is_wechat_platform:
                # 微信平台需要特殊处理
                # 因为微信个人ID通常包含下划线，不适合用通用分割方法
                
                # 但是，如果明确是群聊隔离格式，仍然需要处理
                if "@chatroom_" in session_id:
                    # 这部分已经在上面处理过了
                    pass
                elif ":GroupMessage:" in session_id and "_" in session_id.split(":")[-1]:
                    # 可能是其他格式的群聊隔离
                    parts = session_id.split(":")
                    if len(parts) >= 3:
                        group_parts = parts[-1].rsplit("_", 1)
                        if len(group_parts) == 2:
                            return f"{parts[0]}:{parts[1]}:{group_parts[0]}"
                
                # 如果没有命中上述规则，返回原始ID
                return session_id
            else:
                # 非微信平台，使用通用规则
                parts = session_id.rsplit(":", 1)
                if len(parts) == 2 and "_" in parts[1]:
                    # 查找最后一个下划线，认为这是会话隔离添加的
                    group_id, user_id = parts[1].rsplit("_", 1)
                    return f"{parts[0]}:{group_id}"
        
        # 如果不是隔离格式或无法解析，返回原始ID
        return session_id
    
    def create_at_message(self, reminder: dict, original_msg_origin: str) -> MessageChain:
        """创建@消息"""
        msg = MessageChain()
        
        if not self.is_private_chat(original_msg_origin) and "creator_id" in reminder and reminder["creator_id"]:
            if original_msg_origin.startswith("aiocqhttp"):
                msg.chain.append(At(qq=reminder["creator_id"]))  # QQ平台
            elif any(original_msg_origin.startswith(platform) for platform in self.wechat_platforms):
                # 所有微信平台 - 使用用户名/昵称而不是ID
                if "creator_name" in reminder and reminder["creator_name"]:
                    msg.chain.append(Plain(f"@{reminder['creator_name']} "))
                else:
                    # 如果没有保存用户名，尝试使用ID
                    msg.chain.append(Plain(f"@{reminder['creator_id']} "))
            else:
                # 其他平台的@实现
                msg.chain.append(Plain(f"@{reminder['creator_id']} "))
        
        return msg
    
    async def send_reminder_message(self, unified_msg_origin: str, reminder: dict, content: str, is_task: bool = False):
        """发送提醒消息"""
        original_msg_origin = self.get_original_session_id(unified_msg_origin)
        
        # 构建消息链
        msg = self.create_at_message(reminder, original_msg_origin)
        
        # 添加内容
        if is_task:
            msg.chain.append(Plain(content))
        else:
            msg.chain.append(Plain("[提醒] " + content))
        
        logger.info(f"尝试发送{'任务' if is_task else '提醒'}消息到: {original_msg_origin} (原始ID: {unified_msg_origin})")
        send_result = await self.context.send_message(original_msg_origin, msg)
        logger.info(f"消息发送结果: {send_result}")
        
        return send_result


class TaskExecutor:
    """处理任务执行相关的功能"""
    
    def __init__(self, context, wechat_platforms):
        self.context = context
        self.wechat_platforms = wechat_platforms
        self.message_handler = ReminderMessageHandler(context, wechat_platforms)
    
    def _apply_safe_session_parser(self):
        """应用安全的会话解析器补丁"""
        try:
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
                        # 正确分割，避免 "too many values to unpack" 错误
                        parts = session_str.split(":")
                        platform = parts[0]
                        
                        # 智能判断消息类型
                        if "FriendMessage" in session_str:
                            message_type = "FriendMessage"
                        elif "GroupMessage" in session_str:
                            message_type = "GroupMessage"
                        else:
                            message_type = parts[1] if len(parts) > 1 else "FriendMessage"
                            
                        # 将剩余部分重新组合作为session_id
                        session_id = ":".join(parts[2:]) if len(parts) > 2 else "unknown"
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
    
    def _create_platform_helper(self, send_session_id: str):
        """创建平台辅助工具"""
        class PlatformHelperWithSend:
            def __init__(self, context, session_id):
                self.context = context
                self.session_id = session_id
                
            async def send_message(self, message):
                try:
                    return await self.context.send_message(self.session_id, message)
                except Exception as e:
                    logger.error(f"平台工具发送消息失败: {str(e)}")
                    return False
        
        return PlatformHelperWithSend(self.context, send_session_id)
    
    def _ensure_event_attributes(self, event, send_session_id: str, reminder: dict, is_private_chat: bool, platform_name: str):
        """确保事件对象具有所有可能需要的属性"""
        # 添加常用的reply方法
        if not hasattr(event, "reply"):
            async def reply_func(content):
                event._has_send_oper = True
                msg_chain = MessageChain()
                if isinstance(content, str):
                    msg_chain.chain.append(Plain(content))
                else:
                    msg_chain = content
                return await self.context.send_message(send_session_id, msg_chain)
            event.reply = reply_func
        
        # 添加session_id属性
        if not hasattr(event, "session_id"):
            event.session_id = send_session_id
        
        # unified_msg_origin会在AstrMessageEvent构造函数中自动生成，但我们要确保它是正确的
        # 如果需要，可以手动覆盖（但通常不需要）
        # event.unified_msg_origin = send_session_id
        
        # 添加get_session_id方法
        if not hasattr(event, "get_session_id"):
            event.get_session_id = lambda: send_session_id
        
        # 添加get_platform_type方法
        if not hasattr(event, "get_platform_type"):
            event.get_platform_type = lambda: platform_name
        
        # 添加get_message_type方法
        if not hasattr(event, "get_message_type"):
            msg_type = "friend" if is_private_chat else "group"
            event.get_message_type = lambda: msg_type
        
        # 添加get_sender_id方法（如果还没有）
        if hasattr(event, "get_sender_id"):
            original_get_sender = event.get_sender_id
            def safe_get_sender():
                try:
                    return original_get_sender()
                except:
                    return reminder.get("creator_id", "unknown")
            event.get_sender_id = safe_get_sender
        else:
            # 确保返回的是字符串类型的ID
            def get_sender_id():
                sender_id = reminder.get("creator_id", "unknown")
                return str(sender_id) if sender_id else "unknown"
            event.get_sender_id = get_sender_id
        
        # 添加结果管理方法，支持复杂消息类型
        if not hasattr(event, '_result'):
            from astrbot.core.message.message_event_result import MessageEventResult
            event._result = MessageEventResult()
        
        if not hasattr(event, 'get_result'):
            def get_result():
                return event._result
            event.get_result = get_result
        
        if not hasattr(event, 'set_result'):
            def set_result(result):
                if hasattr(result, 'chain'):
                    event._result = result
                else:
                    # 如果是字符串，转换为MessageEventResult
                    from astrbot.core.message.message_event_result import MessageEventResult
                    from astrbot.core.message.components import Plain
                    msg_result = MessageEventResult()
                    msg_result.chain.append(Plain(str(result)))
                    event._result = msg_result
            event.set_result = set_result
    
    def _create_event_object(self, task_text: str, unified_msg_origin: str, reminder: dict, is_private_chat: bool, send_session_id: str):
        """创建事件对象"""
        # 创建基本消息对象
        msg = AstrBotMessage()
        msg.message_str = task_text
        msg.session_id = send_session_id  # 使用发送用的session_id
        msg.type = MessageType.FRIEND_MESSAGE if is_private_chat else MessageType.GROUP_MESSAGE
        
        # 设置机器人自身ID（很多插件可能需要这个）
        msg.self_id = "astrbot_reminder"
        
        # 设置消息链（包含任务文本）
        from astrbot.core.message.components import Plain
        msg.message = [Plain(task_text)]
        
        # 如果有创建者ID，则设置发送者信息
        if "creator_id" in reminder:
            msg.sender = MessageMember(reminder["creator_id"], reminder.get("creator_name", "用户"))
        else:
            msg.sender = MessageMember("unknown", "用户")
        
        # 设置群组ID（如果是群聊）
        if not is_private_chat:
            # 从session_id中提取群组ID
            if ":" in send_session_id:
                parts = send_session_id.split(":")
                if len(parts) >= 3:
                    group_id_part = parts[2]
                    # 处理群组ID，去掉可能的用户隔离后缀
                    if "_" in group_id_part:
                        group_id_part = group_id_part.split("_")[0]
                    msg.group_id = group_id_part
                else:
                    msg.group_id = "unknown"
            else:
                msg.group_id = "unknown"
        else:
            msg.group_id = None
            
        # 不再尝试分割session_id，而是直接使用消息来源标识平台
        platform_name = "unknown"
        if any(unified_msg_origin.startswith(platform) for platform in self.wechat_platforms):
            # 如果是微信相关平台，使用前缀作为平台名称
            for platform in self.wechat_platforms:
                if unified_msg_origin.startswith(platform):
                    platform_name = platform
                    break
        elif ":" in unified_msg_origin:
            # 如果有冒号，尝试获取第一段作为平台名
            platform_name = unified_msg_origin.split(":", 1)[0]

        # 创建事件对象 - 重要：session_id只需要ID部分，不要包含平台前缀
        raw_session_id = send_session_id
        if ":" in send_session_id:
            parts = send_session_id.split(":")
            if len(parts) >= 3:
                raw_session_id = parts[2]  # 只取ID部分
            else:
                raw_session_id = send_session_id
        
        meta = PlatformMetadata(platform_name, "scheduler")
        event = AstrMessageEvent(
            message_str=task_text,
            message_obj=msg,
            platform_meta=meta,
            session_id=raw_session_id  # 只传入纯粹的session_id
        )
        
        # 添加特殊属性，供函数调用时使用
        event._send_session_id = send_session_id
        event._has_send_oper = False
        
        # 添加平台辅助工具到消息对象
        if not hasattr(event.message_obj, "platform"):
            event.message_obj.platform = self._create_platform_helper(send_session_id)
        
        # 确保事件对象具有所有可能需要的属性
        self._ensure_event_attributes(event, send_session_id, reminder, is_private_chat, platform_name)
        
        return event
    
    async def execute_task(self, unified_msg_origin: str, reminder: dict, provider, func_tool):
        """执行任务"""
        task_text = reminder['text']
        logger.info(f"Task Activated: {task_text}, attempting to execute for {unified_msg_origin}")
        
        # 应用安全解析器补丁
        self._apply_safe_session_parser()
        
        try:
            # 获取对话上下文
            original_msg_origin = self.message_handler.get_original_session_id(unified_msg_origin)
            curr_cid = await self.context.conversation_manager.get_curr_conversation_id(original_msg_origin)
            conversation = None
            contexts = []
            
            if curr_cid:
                conversation = await self.context.conversation_manager.get_conversation(original_msg_origin, curr_cid)
                if conversation:
                    contexts = json.loads(conversation.history)
                    logger.info(f"提醒模式：找到用户对话，对话ID: {curr_cid}, 上下文长度: {len(contexts)}")
            
            # 如果没有对话或需要新建对话
            if not curr_cid or not conversation:
                curr_cid = await self.context.conversation_manager.new_conversation(original_msg_origin)
                conversation = await self.context.conversation_manager.get_conversation(original_msg_origin, curr_cid)
                logger.info(f"创建新对话，对话ID: {curr_cid}")
            
            # 检查是否是调用LLM函数的任务
            if task_text.startswith("请调用") and "函数" in task_text:
                prompt = f"用户请求你执行以下操作：{task_text}。请直接执行这个任务，不要解释你在做什么，就像用户刚刚发出这个请求一样。"
            else:
                # 普通任务，直接让AI执行
                prompt = f"请执行以下任务：{task_text}。请直接执行，不要提及这是一个预设任务。"
            
            logger.info(f"发送提示词到LLM: {prompt[:50]}...")
            
            # 添加系统提示词，确保LLM知道它可以调用函数
            system_prompt = "你可以调用各种函数来帮助用户完成任务，如获取天气、设置提醒等。请根据用户的需求直接调用相应的函数。"
            
            # 直接调用LLM，获取响应后手动处理
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
                need_send_result = await self._handle_tool_calls(response, func_tool, task_text, unified_msg_origin, reminder, 
                                            new_contexts, result_msg, need_send_result)
            elif response.role == "assistant" and response.completion_text:
                # 如果只有文本回复，构建普通消息
                result_msg.chain.append(Plain(filter_thinking_content(response.completion_text)))
                # 添加AI的回复到历史记录
                new_contexts.append({"role": "assistant", "content": filter_thinking_content(response.completion_text)})
            else:
                # 没有文本回复也没有工具调用，返回默认消息
                result_msg.chain.append(Plain("任务执行完成，但未返回结果。"))
                # 添加结果到历史记录
                new_contexts.append({"role": "assistant", "content": "任务执行完成，但未返回结果。"})
            
            # 只有在需要时才发送消息
            if need_send_result:
                await self._send_task_result(unified_msg_origin, reminder, result_msg)
            
            # 更新对话历史
            await self._update_conversation_history(original_msg_origin, curr_cid, new_contexts)
            
            logger.info(f"Task executed: {task_text}")
            
        except Exception as e:
            logger.error(f"执行任务时出错: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            
            # 尝试发送错误消息
            error_msg = MessageChain()
            error_msg.chain.append(Plain(f"执行任务时出错: {str(e)}"))
            
            original_msg_origin = self.message_handler.get_original_session_id(unified_msg_origin)
            await self.context.send_message(original_msg_origin, error_msg)
    
    async def _handle_tool_calls(self, response, func_tool, task_text, unified_msg_origin, reminder, 
                                new_contexts, result_msg, need_send_result):
        """处理工具调用"""
        logger.info(f"检测到工具调用: {response.tools_call_name}")
        
        # 收集工具调用结果
        tool_results = []
        has_sent_messages = []  # 记录哪些函数已经自己发送了消息
        complex_messages = []  # 记录函数返回的复杂消息
        
        is_private_chat = self.message_handler.is_private_chat(unified_msg_origin)
        send_session_id = self._get_send_session_id(unified_msg_origin, is_private_chat)
        
        for i, func_name in enumerate(response.tools_call_name):
            func_args = response.tools_call_args[i] if i < len(response.tools_call_args) else {}
            
            logger.info(f"执行工具调用: {func_name}({func_args})")
            
            try:
                # 获取函数对象和处理器
                func_obj = func_tool.get_func(func_name)
                
                if func_obj:
                    # 创建事件对象
                    event = self._create_event_object(task_text, unified_msg_origin, reminder, is_private_chat, send_session_id)
                    
                    # 调用函数
                    try:
                        # 记录调用前的状态
                        has_sent_message_before = event._has_send_oper
                        
                        # 调试信息：记录函数调用的详细参数
                        logger.info(f"调用函数 {func_name}:")
                        logger.info(f"  - func_args: {func_args}")
                        logger.info(f"  - event.unified_msg_origin: {getattr(event, 'unified_msg_origin', 'NOT_SET')}")
                        logger.info(f"  - event.session_id: {getattr(event, 'session_id', 'NOT_SET')}")
                        logger.info(f"  - event.message_obj.group_id: {getattr(event.message_obj, 'group_id', 'NOT_SET')}")
                        logger.info(f"  - event.message_obj.self_id: {getattr(event.message_obj, 'self_id', 'NOT_SET')}")
                        
                        # 调用函数
                        if func_obj.handler:
                            func_result = await func_obj.handler(event, **func_args)
                        else:
                            func_result = await func_obj.execute(**func_args)
                        
                        logger.info(f"函数调用结果类型: {type(func_result)}, 值: {func_result}")
                        
                        # 检查函数是否已经自己发送了消息
                        if event._has_send_oper and not has_sent_message_before:
                            logger.info(f"函数 {func_name} 已自行发送消息，不需要我们再发送")
                            has_sent_messages.append(func_name)
                        
                        # 检查函数是否通过event.set_result()设置了复杂消息结果
                        event_result = None
                        if hasattr(event, 'get_result') and callable(event.get_result):
                            event_result = event.get_result()
                        elif hasattr(event, '_result'):
                            event_result = event._result
                        
                        # 处理复杂消息结果
                        if event_result and hasattr(event_result, 'chain') and event_result.chain:
                            logger.info(f"函数 {func_name} 返回了复杂消息结果，包含 {len(event_result.chain)} 个组件")
                            complex_messages.append({
                                "name": func_name,
                                "message_chain": event_result
                            })
                            has_sent_messages.append(func_name)  # 标记为已处理
                        # 处理简单的字符串返回值
                        elif func_result is not None and func_name not in has_sent_messages:
                            # 检查返回值是否是MessageEventResult对象
                            if hasattr(func_result, 'chain'):
                                logger.info(f"函数 {func_name} 返回了MessageEventResult对象")
                                complex_messages.append({
                                    "name": func_name,
                                    "message_chain": func_result
                                })
                                has_sent_messages.append(func_name)
                            else:
                                # 简单字符串结果
                                tool_results.append({
                                    "name": func_name,
                                    "result": str(func_result)
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
        
        # 处理复杂消息（图片、文件等）
        if complex_messages:
            await self._handle_complex_messages(complex_messages, unified_msg_origin, reminder)
        
        # 函数处理逻辑结束后判断是否需要发送结果
        # 如果所有函数都已经自己发送了消息，我们就不需要再发送了
        if len(has_sent_messages) == len(response.tools_call_name):
            logger.info("所有函数都已自行发送消息，不需要额外发送结果")
            return False  # 返回不需要发送结果
        # 如果只有部分函数自己发送了消息，我们只润色没有自己发送消息的函数的结果
        elif tool_results:
            await self._process_tool_results(tool_results, task_text, unified_msg_origin, new_contexts, result_msg)
            return True  # 返回需要发送结果
        else:
            # 没有工具调用结果
            if has_sent_messages:
                # 如果有函数自己发送了消息，我们不需要再发送额外的消息
                return False  # 返回不需要发送结果
            else:
                result_msg.chain.append(Plain("任务执行完成，但未能获取有效结果。"))
                # 添加结果到历史记录
                new_contexts.append({"role": "assistant", "content": "任务执行完成，但未能获取有效结果。"})
                return True  # 返回需要发送结果
    
    async def _handle_complex_messages(self, complex_messages: list, unified_msg_origin: str, reminder: dict):
        """处理复杂消息类型（图片、文件、视频等）"""
        import asyncio
        from astrbot.core.message.components import Plain, Image, File, Video, Record, At, Share
        
        for msg_info in complex_messages:
            func_name = msg_info["name"]
            message_chain = msg_info["message_chain"]
            
            logger.info(f"处理函数 {func_name} 的复杂消息，包含 {len(message_chain.chain)} 个组件")
            
            # 创建新的消息链
            final_msg = MessageChain()
            
            # 添加@消息（复用现有逻辑）
            original_msg_origin = self.message_handler.get_original_session_id(unified_msg_origin)
            if not self.message_handler.is_private_chat(unified_msg_origin) and "creator_id" in reminder and reminder["creator_id"]:
                if original_msg_origin.startswith("aiocqhttp"):
                    final_msg.chain.append(At(qq=reminder["creator_id"]))
                elif any(original_msg_origin.startswith(platform) for platform in self.wechat_platforms):
                    if "creator_name" in reminder and reminder["creator_name"]:
                        final_msg.chain.append(Plain(f"@{reminder['creator_name']} "))
                    else:
                        final_msg.chain.append(Plain(f"@{reminder['creator_id']} "))
                else:
                    final_msg.chain.append(Plain(f"@{reminder['creator_id']} "))
            
            # 处理消息链中的每个组件
            text_parts = []  # 收集文本部分
            
            for component in message_chain.chain:
                if isinstance(component, Plain):
                    text_parts.append(component.text)
                elif isinstance(component, Image):
                    # 先发送累积的文本（如果有）
                    if text_parts:
                        final_msg.chain.append(Plain("".join(text_parts)))
                        text_parts = []
                    
                    # 添加图片组件
                    final_msg.chain.append(component)
                    
                    # 发送这条消息
                    await self._send_complex_message(final_msg, original_msg_origin, func_name, "图片")
                    
                    # 添加发送间隔，避免被限流
                    await asyncio.sleep(0.5)
                    
                    # 重置消息链（保留@部分）
                    final_msg = MessageChain()
                    if not self.message_handler.is_private_chat(unified_msg_origin) and "creator_id" in reminder and reminder["creator_id"]:
                        if original_msg_origin.startswith("aiocqhttp"):
                            final_msg.chain.append(At(qq=reminder["creator_id"]))
                        elif any(original_msg_origin.startswith(platform) for platform in self.wechat_platforms):
                            if "creator_name" in reminder and reminder["creator_name"]:
                                final_msg.chain.append(Plain(f"@{reminder['creator_name']} "))
                            else:
                                final_msg.chain.append(Plain(f"@{reminder['creator_id']} "))
                        else:
                            final_msg.chain.append(Plain(f"@{reminder['creator_id']} "))
                
                elif isinstance(component, File):
                    # 先发送累积的文本（如果有）
                    if text_parts:
                        final_msg.chain.append(Plain("".join(text_parts)))
                        text_parts = []
                    
                    # 添加文件组件
                    final_msg.chain.append(component)
                    
                    # 发送这条消息
                    await self._send_complex_message(final_msg, original_msg_origin, func_name, "文件")
                    
                    # 添加发送间隔，避免被限流
                    await asyncio.sleep(0.5)
                    
                    # 重置消息链
                    final_msg = MessageChain()
                    if not self.message_handler.is_private_chat(unified_msg_origin) and "creator_id" in reminder and reminder["creator_id"]:
                        if original_msg_origin.startswith("aiocqhttp"):
                            final_msg.chain.append(At(qq=reminder["creator_id"]))
                        elif any(original_msg_origin.startswith(platform) for platform in self.wechat_platforms):
                            if "creator_name" in reminder and reminder["creator_name"]:
                                final_msg.chain.append(Plain(f"@{reminder['creator_name']} "))
                            else:
                                final_msg.chain.append(Plain(f"@{reminder['creator_id']} "))
                        else:
                            final_msg.chain.append(Plain(f"@{reminder['creator_id']} "))
                
                elif isinstance(component, Video):
                    # 先发送累积的文本（如果有）
                    if text_parts:
                        final_msg.chain.append(Plain("".join(text_parts)))
                        text_parts = []
                    
                    # 添加视频组件
                    final_msg.chain.append(component)
                    
                    # 发送这条消息
                    await self._send_complex_message(final_msg, original_msg_origin, func_name, "视频")
                    
                    # 添加发送间隔，避免被限流
                    await asyncio.sleep(0.5)
                    
                    # 重置消息链
                    final_msg = MessageChain()
                    if not self.message_handler.is_private_chat(unified_msg_origin) and "creator_id" in reminder and reminder["creator_id"]:
                        if original_msg_origin.startswith("aiocqhttp"):
                            final_msg.chain.append(At(qq=reminder["creator_id"]))
                        elif any(original_msg_origin.startswith(platform) for platform in self.wechat_platforms):
                            if "creator_name" in reminder and reminder["creator_name"]:
                                final_msg.chain.append(Plain(f"@{reminder['creator_name']} "))
                            else:
                                final_msg.chain.append(Plain(f"@{reminder['creator_id']} "))
                        else:
                            final_msg.chain.append(Plain(f"@{reminder['creator_id']} "))
                
                elif isinstance(component, Record):
                    # 先发送累积的文本（如果有）
                    if text_parts:
                        final_msg.chain.append(Plain("".join(text_parts)))
                        text_parts = []
                    
                    # 添加语音组件
                    final_msg.chain.append(component)
                    
                    # 发送这条消息
                    await self._send_complex_message(final_msg, original_msg_origin, func_name, "语音")
                    
                    # 添加发送间隔，避免被限流
                    await asyncio.sleep(0.5)
                    
                    # 重置消息链
                    final_msg = MessageChain()
                    if not self.message_handler.is_private_chat(unified_msg_origin) and "creator_id" in reminder and reminder["creator_id"]:
                        if original_msg_origin.startswith("aiocqhttp"):
                            final_msg.chain.append(At(qq=reminder["creator_id"]))
                        elif any(original_msg_origin.startswith(platform) for platform in self.wechat_platforms):
                            if "creator_name" in reminder and reminder["creator_name"]:
                                final_msg.chain.append(Plain(f"@{reminder['creator_name']} "))
                            else:
                                final_msg.chain.append(Plain(f"@{reminder['creator_id']} "))
                        else:
                            final_msg.chain.append(Plain(f"@{reminder['creator_id']} "))
                
                elif isinstance(component, Share):
                    # 先发送累积的文本（如果有）
                    if text_parts:
                        final_msg.chain.append(Plain("".join(text_parts)))
                        text_parts = []
                    
                    # 添加分享组件
                    final_msg.chain.append(component)
                    
                    # 发送这条消息
                    await self._send_complex_message(final_msg, original_msg_origin, func_name, "分享")
                    
                    # 添加发送间隔，避免被限流
                    await asyncio.sleep(0.5)
                    
                    # 重置消息链
                    final_msg = MessageChain()
                    if not self.message_handler.is_private_chat(unified_msg_origin) and "creator_id" in reminder and reminder["creator_id"]:
                        if original_msg_origin.startswith("aiocqhttp"):
                            final_msg.chain.append(At(qq=reminder["creator_id"]))
                        elif any(original_msg_origin.startswith(platform) for platform in self.wechat_platforms):
                            if "creator_name" in reminder and reminder["creator_name"]:
                                final_msg.chain.append(Plain(f"@{reminder['creator_name']} "))
                            else:
                                final_msg.chain.append(Plain(f"@{reminder['creator_id']} "))
                        else:
                            final_msg.chain.append(Plain(f"@{reminder['creator_id']} "))
                
                else:
                    # 对于其他类型的组件，尝试直接添加
                    logger.warning(f"处理未知消息组件类型: {type(component)}")
                    final_msg.chain.append(component)
            
            # 发送剩余的文本（如果有）
            if text_parts:
                final_msg.chain.append(Plain("".join(text_parts)))
            
            # 如果最终消息链中有内容（除了@之外），发送它
            if len(final_msg.chain) > 1 or (len(final_msg.chain) == 1 and not isinstance(final_msg.chain[0], (At, Plain))):
                await self._send_complex_message(final_msg, original_msg_origin, func_name, "其他")
    
    async def _send_complex_message(self, message_chain: MessageChain, original_msg_origin: str, func_name: str, message_type: str):
        """发送复杂消息"""
        try:
            logger.info(f"发送{message_type}消息到: {original_msg_origin} (来自函数: {func_name})")
            send_result = await self.context.send_message(original_msg_origin, message_chain)
            logger.info(f"{message_type}消息发送结果: {send_result}")
        except Exception as e:
            logger.error(f"发送{message_type}消息失败: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            
            # 如果发送失败，尝试发送文本描述
            try:
                fallback_msg = MessageChain()
                fallback_msg.chain.append(Plain(f"[{message_type}消息发送失败: {str(e)}]"))
                await self.context.send_message(original_msg_origin, fallback_msg)
            except Exception as e2:
                logger.error(f"发送备用消息也失败: {str(e2)}")
    
    def _get_send_session_id(self, unified_msg_origin: str, is_private_chat: bool) -> str:
        """获取发送会话ID"""
        if ":" in unified_msg_origin:
            # 优先使用原始会话ID（去除用户隔离部分）
            send_session_id = self.message_handler.get_original_session_id(unified_msg_origin)
            
            # 如果格式不对，尝试其他方式
            if len(send_session_id.split(":")) < 2:
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
            platform_name = "unknown"
            if any(unified_msg_origin.startswith(platform) for platform in self.wechat_platforms):
                for platform in self.wechat_platforms:
                    if unified_msg_origin.startswith(platform):
                        platform_name = platform
                        break
            elif ":" in unified_msg_origin:
                platform_name = unified_msg_origin.split(":", 1)[0]
            
            msg_type = "FriendMessage" if is_private_chat else "GroupMessage"
            send_session_id = f"{platform_name}:{msg_type}:unknown"
        
        return send_session_id
    
    async def _process_tool_results(self, tool_results, task_text, unified_msg_origin, new_contexts, result_msg):
        """处理工具调用结果"""
        # 如果有函数调用结果，让LLM润色结果
        # 构建提示词，让LLM基于工具调用结果生成自然语言响应
        tool_results_text = ""
        for tr in tool_results:
            tool_results_text += f"- {tr['name']}: {tr['result']}\n"
        
        summary_prompt = f"""我执行了用户的任务"{task_text}"，并获得了以下结果：
        
{tool_results_text}

请对这些结果进行整理和润色，用自然、友好的语言向用户展示这些信息。直接回复用户的问题，不要提及这是定时任务或使用了什么函数。"""
        
        # 获取提供商
        provider = self.context.get_using_provider()
        
        # 使用LLM润色结果，不使用函数调用
        summary_response = await provider.text_chat(
            prompt=summary_prompt,
            session_id=unified_msg_origin,
            contexts=[]  # 不使用上下文，避免混淆
        )
        
        if summary_response and summary_response.completion_text:
            result_msg.chain.append(Plain(filter_thinking_content(summary_response.completion_text)))
            # 添加AI的回复到历史记录
            new_contexts.append({"role": "assistant", "content": filter_thinking_content(summary_response.completion_text)})
        else:
            # 如果润色失败，直接显示原始结果
            result_text = "执行结果:\n"
            for tr in tool_results:
                result_text += f"[{tr['name']}]: {tr['result']}\n"
            result_msg.chain.append(Plain(result_text))
            # 添加结果到历史记录
            new_contexts.append({"role": "assistant", "content": result_text})
    
    async def _send_task_result(self, unified_msg_origin: str, reminder: dict, result_msg: MessageChain):
        """发送任务结果"""
        # 获取原始消息ID（去除用户隔离部分）
        original_msg_origin = self.message_handler.get_original_session_id(unified_msg_origin)
        logger.info(f"尝试发送消息到: {original_msg_origin} (原始ID: {unified_msg_origin})")
        
        # 构建最终的消息链，先添加@再添加结果
        final_msg = MessageChain()
        
        # 添加@，复用提醒模式中的@逻辑
        if not self.message_handler.is_private_chat(unified_msg_origin) and "creator_id" in reminder and reminder["creator_id"]:
            if original_msg_origin.startswith("aiocqhttp"):
                final_msg.chain.append(At(qq=reminder["creator_id"]))  # QQ平台
            elif any(original_msg_origin.startswith(platform) for platform in self.wechat_platforms):
                # 所有微信平台 - 使用用户名/昵称而不是ID
                if "creator_name" in reminder and reminder["creator_name"]:
                    final_msg.chain.append(Plain(f"@{reminder['creator_name']} "))
                else:
                    # 如果没有保存用户名，尝试使用ID
                    final_msg.chain.append(Plain(f"@{reminder['creator_id']} "))
            else:
                # 其他平台的@实现
                final_msg.chain.append(Plain(f"@{reminder['creator_id']} "))
        
        # 添加结果消息内容
        for item in result_msg.chain:
            final_msg.chain.append(item)
        
        send_result = await self.context.send_message(original_msg_origin, final_msg)
        logger.info(f"消息发送结果: {send_result}")
    
    async def _update_conversation_history(self, original_msg_origin: str, curr_cid: str, new_contexts: list):
        """更新对话历史"""
        try:
            # 获取原始消息ID（去除用户隔离部分）
            original_msg_origin = self.message_handler.get_original_session_id(original_msg_origin)
            
            # 更新对话历史
            await self.context.conversation_manager.update_conversation(
                original_msg_origin, 
                curr_cid, 
                history=new_contexts
            )
            logger.info(f"提醒已添加到对话历史，对话ID: {curr_cid}")
        except Exception as e:
            logger.error(f"更新提醒对话历史失败: {str(e)}")


class ReminderExecutor:
    """处理提醒执行相关的功能"""
    
    def __init__(self, context, wechat_platforms):
        self.context = context
        self.wechat_platforms = wechat_platforms
        self.message_handler = ReminderMessageHandler(context, wechat_platforms)
    
    async def execute_reminder(self, unified_msg_origin: str, reminder: dict, provider):
        """执行提醒"""
        logger.info(f"Reminder Activated: {reminder['text']}, created by {unified_msg_origin}")
        
        # 获取对话上下文，以便LLM生成更自然的回复
        try:
            # 获取原始消息ID（去除用户隔离部分）
            original_msg_origin = self.message_handler.get_original_session_id(unified_msg_origin)
            curr_cid = await self.context.conversation_manager.get_curr_conversation_id(original_msg_origin)
            conversation = None
            contexts = []
            
            if curr_cid:
                conversation = await self.context.conversation_manager.get_conversation(original_msg_origin, curr_cid)
                if conversation:
                    contexts = json.loads(conversation.history)
                    logger.info(f"提醒模式：找到用户对话，对话ID: {curr_cid}, 上下文长度: {len(contexts)}")
        except Exception as e:
            logger.warning(f"提醒模式：获取对话上下文失败: {str(e)}")
            contexts = []
        
        # 构建更丰富的提醒提示词
        user_name = reminder.get("user_name", "用户")
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # 基于上下文量身定制提示词
        if len(contexts) > 2:
            # 有对话历史，可以更自然地引入提醒
            prompt = f"""你现在需要向{user_name}发送一条预设的提醒。

当前时间是 {current_time}
提醒内容: {reminder['text']}

考虑到用户最近的对话内容，请以自然、友好的方式插入这条提醒。可以根据用户的聊天风格调整你的语气，但确保提醒内容清晰传达。
如果提醒内容与最近对话有关联，可以建立连接；如果无关，可以用适当的过渡语引入。

直接输出你要发送的提醒内容，无需说明这是提醒。"""
        else:
            # 没有太多对话历史，使用变化的表达方式
            reminder_styles = [
                f"嘿，{user_name}！这是你设置的提醒：{reminder['text']}",
                f"提醒时间到了！{reminder['text']}",
                f"别忘了：{reminder['text']}",
                f"温馨提醒，{user_name}：{reminder['text']}",
                f"时间提醒：{reminder['text']}",
                f"叮咚！{reminder['text']}",
            ]
            chosen_style = random.choice(reminder_styles)
            prompt = f"""你需要提醒用户"{reminder['text']}"。
请以自然、友好的方式表达这个提醒，可以参考但不限于这种表达方式："{chosen_style}"。
根据提醒的内容，调整你的表达，使其听起来自然且贴心。直接输出你要发送的提醒内容，无需说明这是提醒。"""
        
        response = await provider.text_chat(
            prompt=prompt,
            session_id=unified_msg_origin,
            contexts=contexts[:5] if contexts else []  # 使用最近的5条对话作为上下文
        )
        
        # 发送提醒消息
        await self.message_handler.send_reminder_message(unified_msg_origin, reminder, filter_thinking_content(response.completion_text), is_task=False)
        
        # 如果有对话上下文，记录这次提醒到对话历史
        if curr_cid and conversation:
            try:
                new_contexts = contexts.copy()
                # 添加系统消息表示这是一个提醒
                new_contexts.append({"role": "system", "content": f"系统在 {current_time} 触发了提醒: {reminder['text']}"})
                # 添加AI的回复
                new_contexts.append({"role": "assistant", "content": filter_thinking_content(response.completion_text)})
                
                # 获取原始消息ID（去除用户隔离部分）
                original_msg_origin = self.message_handler.get_original_session_id(unified_msg_origin)
                
                # 更新对话历史
                await self.context.conversation_manager.update_conversation(
                    original_msg_origin, 
                    curr_cid, 
                    history=new_contexts
                )
                logger.info(f"提醒已添加到对话历史，对话ID: {curr_cid}")
            except Exception as e:
                logger.error(f"更新提醒对话历史失败: {str(e)}")


class SimpleMessageSender:
    """处理简单消息发送"""
    
    def __init__(self, context, wechat_platforms):
        self.context = context
        self.wechat_platforms = wechat_platforms
        self.message_handler = ReminderMessageHandler(context, wechat_platforms)
    
    async def send_simple_message(self, unified_msg_origin: str, reminder: dict, is_task: bool = False):
        """发送简单消息（当没有提供商时使用）"""
        logger.warning(f"没有可用的提供商，使用简单消息")
        
        # 构建基础消息链
        msg = MessageChain()
        
        # 如果不是私聊且存在创建者ID，则添加@（明确使用私聊判断）
        if not self.message_handler.is_private_chat(unified_msg_origin) and "creator_id" in reminder and reminder["creator_id"]:
            if unified_msg_origin.startswith("aiocqhttp"):
                msg.chain.append(At(qq=reminder["creator_id"]))  # QQ平台
            elif any(unified_msg_origin.startswith(platform) for platform in self.wechat_platforms):
                # 所有微信平台 - 使用用户名/昵称而不是ID
                if "creator_name" in reminder and reminder["creator_name"]:
                    msg.chain.append(Plain(f"@{reminder['creator_name']} "))
                else:
                    # 如果没有保存用户名，尝试使用ID
                    msg.chain.append(Plain(f"@{reminder['creator_id']} "))
            else:
                # 其他平台的@实现
                msg.chain.append(Plain(f"@{reminder['creator_id']} "))
        
        prefix = "任务: " if is_task else "提醒: "
        msg.chain.append(Plain(f"{prefix}{reminder['text']}"))
        
        # 获取原始消息ID（去除用户隔离部分）
        original_msg_origin = self.message_handler.get_original_session_id(unified_msg_origin)
        logger.info(f"尝试发送简单消息到: {original_msg_origin} (原始ID: {unified_msg_origin})")
        
        send_result = await self.context.send_message(original_msg_origin, msg)
        logger.info(f"消息发送结果: {send_result}")
        
        return send_result