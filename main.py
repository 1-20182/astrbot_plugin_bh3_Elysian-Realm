# -*- coding: utf-8 -*-
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp
import random
import os

from .data_manager import CCBDataManager, UserRecord

# 数据文件路径
DATA_FILE = os.path.join(os.getcwd(), "data", "plugins", "astrbot_plugin_ccb", "jilu.json")

# 特殊用户ID（拒绝CCB）
BLOCKED_USER_ID = "2155498295"


def get_avatar_url(user_id: str) -> str:
    """获取用户头像URL"""
    return f"https://q4.qlogo.cn/headimg_dl?dst_uin={user_id}&spec=640"


async def get_nickname(event: AstrMessageEvent, user_id: str) -> str:
    """
    获取用户昵称

    Args:
        event: 消息事件
        user_id: 用户ID

    Returns:
        用户昵称，获取失败则返回用户ID
    """
    try:
        if event.get_platform_name() == "aiocqhttp":
            from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
            assert isinstance(event, AiocqhttpMessageEvent)
            client = event.bot
            stranger_payloads = {"user_id": user_id}
            stranger_info: dict = await client.api.call_action('get_stranger_info', **stranger_payloads)
            return stranger_info.get('nick', user_id)
    except Exception as e:
        logger.warning(f"获取用户昵称失败: {e}")
    return user_id


def calculate_favorability(vol: float) -> float:
    """
    计算好感度

    Args:
        vol: 用户的累积注入量（ml）

    Returns:
        好感度值（上限为10000）
    """
    # 好感度 = vol值的0.001%值的五分之一
    # 即: vol × 0.001% × (1/5)
    favorability = vol * 0.00001 * 0.2
    # 设置上限为10000
    favorability = min(favorability, 10000)
    return round(favorability, 2)


def calculate_lewdness(vol: float) -> float:
    """
    计算淫乱度

    Args:
        vol: 用户的累积注入量（ml）

    Returns:
        淫乱度值
    """
    # 淫乱度 = vol值的0.5%
    # 即: vol × 0.5%
    lewdness = vol * 0.005
    return round(lewdness, 2)


def get_group_id(event: AstrMessageEvent) -> str:
    """
    获取群聊ID

    Args:
        event: 消息事件

    Returns:
        群聊ID，如果不是群聊则返回 "private"
    """
    try:
        # 尝试从事件中获取群聊ID
        if hasattr(event, 'message_obj') and event.message_obj:
            message_obj = event.message_obj
            # 检查是否有 group_id 属性
            if hasattr(message_obj, 'group_id') and message_obj.group_id:
                return str(message_obj.group_id)
            # 检查 message 中是否有 group_id
            if hasattr(message_obj, 'message') and message_obj.message:
                msg = message_obj.message
                if isinstance(msg, dict) and 'group_id' in msg:
                    return str(msg['group_id'])

        # 尝试从 raw_message 中获取
        if hasattr(event, 'raw_message') and event.raw_message:
            raw = event.raw_message
            if isinstance(raw, dict):
                if 'group_id' in raw:
                    return str(raw['group_id'])

        # 尝试从 event 的 group_id 属性获取
        if hasattr(event, 'group_id') and event.group_id:
            return str(event.group_id)

    except Exception as e:
        logger.debug(f"获取群聊ID失败: {e}")

    return "private"


@register("astrbot_plugin_ccb_remake", "飞翔的死猪", "增加了ccb的功能~ 加了淫乱度查询 加了好感查询 加了群排行", "1.4.0")
class CCBPlugin(Star):
    """CCB插件主类"""

    def __init__(self, context: Context):
        super().__init__(context)
        # 初始化数据管理器
        self.data_manager = CCBDataManager(DATA_FILE)
        logger.info("CCB插件已加载，数据管理器初始化完成")

    @filter.command("ccb")
    async def ccb(self, event: AstrMessageEvent):
        """
        CCB命令处理

        使用方式:
        /ccb @某人 - 与指定用户CCB
        /ccb - 与自己CCB
        """
        messages = event.get_messages()
        send_id = event.get_sender_id()
        self_id = event.get_self_id()
        group_id = get_group_id(event)

        # 获取目标用户ID（@的用户或自己）
        target_user_id = next(
            (str(seg.qq) for seg in messages
             if isinstance(seg, Comp.At) and str(seg.qq) != self_id),
            send_id
        )

        # 检查是否是被屏蔽的用户
        if target_user_id == BLOCKED_USER_ID:
            yield event.plain_result("对方拒绝和你ccb")
            return

        # 生成随机数据
        duration = round(random.uniform(1, 60), 2)   # 持续时间（分钟）
        volume = round(random.uniform(1, 100), 2)    # 注入量（ml）

        try:
            # 获取用户昵称
            nickname = await get_nickname(event, target_user_id)

            # 检查用户是否已存在（全局数据）
            if self.data_manager.user_exists(target_user_id):
                # 更新已有用户记录
                record = self.data_manager.update_user(target_user_id, num_delta=1, vol_delta=volume)
                base_text = f"你和{nickname}发生了{duration}min长的ccb行为，向ta注入了{volume}ml的生命因子"
                result_text = f"这是ta的第{record.num}次。ta被累积注入了{record.vol}ml的生命因子"
            else:
                # 创建新用户记录
                record = self.data_manager.add_user(target_user_id, num=1, vol=volume)
                base_text = f"你和{nickname}发生了{duration}min长的ccb行为，向ta注入了{volume}ml的生命因子"
                result_text = "这是ta的初体验。"

            # 记录用户到当前群聊的排行榜
            self.data_manager.record_user_in_group(target_user_id, group_id)

            # 构建消息链
            chain = [Comp.Plain(base_text)]
            
            # 尝试添加头像，但如果失败不影响整体功能
            try:
                avatar_url = get_avatar_url(target_user_id)
                chain.append(Comp.Image.fromURL(avatar_url))
            except Exception as e:
                logger.warning(f"添加头像失败: {e}")
                # 头像获取失败，继续执行，不添加头像

            chain.append(Comp.Plain(result_text))
            yield event.chain_result(chain)

        except Exception as e:
            logger.error(f"CCB处理出错: {e}")
            yield event.plain_result("对方拒绝了和你ccb")

    @filter.command("ccb查询")
    async def query_ccb(self, event: AstrMessageEvent):
        """
        查询CCB记录

        使用方式:
        /ccb查询 @某人 - 查询指定用户的记录
        /ccb查询 - 查询自己的记录
        """
        messages = event.get_messages()
        send_id = event.get_sender_id()
        self_id = event.get_self_id()

        # 获取目标用户ID
        target_user_id = next(
            (str(seg.qq) for seg in messages
             if isinstance(seg, Comp.At) and str(seg.qq) != self_id),
            send_id
        )

        try:
            nickname = await get_nickname(event, target_user_id)
            # 查询全局记录
            record = self.data_manager.get_user_record(target_user_id)

            if record:
                # 构建消息链
                chain = [Comp.Plain(f"用户: {nickname}\n")]
                
                # 尝试添加头像
                try:
                    avatar_url = get_avatar_url(target_user_id)
                    chain.append(Comp.Image.fromURL(avatar_url))
                except Exception as e:
                    logger.warning(f"添加头像失败: {e}")

                chain.append(Comp.Plain(f"CCB次数: {record.num}次\n累计注入: {record.vol}ml"))
                yield event.chain_result(chain)
            else:
                yield event.plain_result(f"{nickname}还没有ccb记录呢~")

        except Exception as e:
            logger.error(f"查询CCB记录出错: {e}")
            yield event.plain_result("查询失败，请稍后再试")

    @filter.command("好感度查询")
    async def query_favorability(self, event: AstrMessageEvent):
        """
        查询好感度

        使用方式:
        /好感度查询 @某人 - 查询指定用户的好感度
        /好感度查询 - 查询自己的好感度
        """
        messages = event.get_messages()
        send_id = event.get_sender_id()
        self_id = event.get_self_id()

        # 获取目标用户ID
        target_user_id = next(
            (str(seg.qq) for seg in messages
             if isinstance(seg, Comp.At) and str(seg.qq) != self_id),
            send_id
        )

        try:
            nickname = await get_nickname(event, target_user_id)
            # 查询全局记录
            record = self.data_manager.get_user_record(target_user_id)

            if record:
                # 计算好感度
                favorability = calculate_favorability(record.vol)
                
                # 构建消息链
                chain = [Comp.Plain(f"用户: {nickname}\n")]
                
                # 尝试添加头像
                try:
                    avatar_url = get_avatar_url(target_user_id)
                    chain.append(Comp.Image.fromURL(avatar_url))
                except Exception as e:
                    logger.warning(f"添加头像失败: {e}")

                chain.append(Comp.Plain(f"好感度: {favorability}\n计算方式: 累积注入量的0.001%的五分之一"))
                yield event.chain_result(chain)
            else:
                yield event.plain_result(f"{nickname}还没有ccb记录呢~")

        except Exception as e:
            logger.error(f"查询好感度出错: {e}")
            yield event.plain_result("查询失败，请稍后再试")

    @filter.command("淫乱度查询")
    async def query_lewdness(self, event: AstrMessageEvent):
        """
        查询淫乱度

        使用方式:
        /淫乱度查询 @某人 - 查询指定用户的淫乱度
        /淫乱度查询 - 查询自己的淫乱度
        """
        messages = event.get_messages()
        send_id = event.get_sender_id()
        self_id = event.get_self_id()

        # 获取目标用户ID
        target_user_id = next(
            (str(seg.qq) for seg in messages
             if isinstance(seg, Comp.At) and str(seg.qq) != self_id),
            send_id
        )

        try:
            nickname = await get_nickname(event, target_user_id)
            # 查询全局记录
            record = self.data_manager.get_user_record(target_user_id)

            if record:
                # 计算淫乱度
                lewdness = calculate_lewdness(record.vol)

                # 构建消息链
                chain = [Comp.Plain(f"用户: {nickname}\n")]

                # 尝试添加头像
                try:
                    avatar_url = get_avatar_url(target_user_id)
                    chain.append(Comp.Image.fromURL(avatar_url))
                except Exception as e:
                    logger.warning(f"添加头像失败: {e}")

                chain.append(Comp.Plain(f"淫乱度: {lewdness}\n计算方式: 累积注入量的0.5%"))
                yield event.chain_result(chain)
            else:
                yield event.plain_result(f"{nickname}还没有ccb记录呢~")

        except Exception as e:
            logger.error(f"查询淫乱度出错: {e}")
            yield event.plain_result("查询失败，请稍后再试")

    @filter.command("ccb排行")
    async def ccb_ranking(self, event: AstrMessageEvent):
        """
        CCB排行榜

        使用方式:
        /ccb排行 - 显示当前群聊的CCB次数排行榜前10名
        """
        group_id = get_group_id(event)

        try:
            # 获取当前群聊的排行榜
            rankings = self.data_manager.get_ranking(limit=10, group_id=group_id)

            if not rankings:
                yield event.plain_result("还没有任何ccb记录呢~")
                return

            result_lines = ["🏆 CCB排行榜 🏆", ""]

            for idx, record in enumerate(rankings, 1):
                nickname = await get_nickname(event, record.id)
                medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(idx, f"{idx}.")
                result_lines.append(f"{medal} {nickname} - {record.num}次 ({record.vol}ml)")

            yield event.plain_result("\n".join(result_lines))

        except Exception as e:
            logger.error(f"获取排行榜出错: {e}")
            yield event.plain_result("获取排行榜失败，请稍后再试")
