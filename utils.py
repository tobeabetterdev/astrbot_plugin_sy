import datetime
import json
import os
from astrbot.api import logger

def parse_datetime(datetime_str: str) -> str:
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

def is_outdated(reminder: dict) -> bool:
    '''检查提醒是否过期'''
    if "datetime" in reminder:
        return datetime.datetime.strptime(reminder["datetime"], "%Y-%m-%d %H:%M") < datetime.datetime.now()
    return False

def load_reminder_data(data_file: str) -> dict:
    '''加载提醒数据'''
    if not os.path.exists(data_file):
        with open(data_file, "w", encoding='utf-8') as f:
            f.write("{}")
    with open(data_file, "r", encoding='utf-8') as f:
        return json.load(f)

async def save_reminder_data(data_file: str, reminder_data: dict):
    '''保存提醒数据'''
    # 在保存前清理过期的一次性任务
    for group in list(reminder_data.keys()):
        reminder_data[group] = [
            r for r in reminder_data[group] 
            if not (r.get("repeat", "none") == "none" and is_outdated(r))
        ]
        # 如果群组没有任何提醒了，删除这个群组的条目
        if not reminder_data[group]:
            del reminder_data[group]
            
    with open(data_file, "w", encoding='utf-8') as f:
        json.dump(reminder_data, f, ensure_ascii=False) 