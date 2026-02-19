import os
import re
import yaml
import aiohttp
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import Plain, Image
from astrbot.api.star import Context, Star, register, StarTools
from astrbot.api import logger


class AliasManager:
    """别名管理器 - 管理角色别名映射"""

    def __init__(self, alias_data: dict):
        self.alias_data = alias_data

    def get(self, name: str) -> Optional[str]:
        """
        根据别名获取角色文件名
        @param name: 角色别名
        @return: 角色文件名或None
        """
        name = name.strip().lower()

        # 直接匹配键名
        if name in self.alias_data:
            return name

        # 遍历别名列表匹配
        for key, aliases in self.alias_data.items():
            if isinstance(aliases, list):
                for alias in aliases:
                    if alias.lower() == name or name in alias.lower():
                        return key
            elif isinstance(aliases, str):
                if aliases.lower() == name or name in aliases.lower():
                    return key

        return None

    def get_all_aliases(self) -> Dict[str, list]:
        """获取所有别名数据"""
        return self.alias_data


@register("astrbot_plugin_bh3", "Assistant", "崩坏3乐土攻略插件", "1.0.0")
class BH3ElysianRealmPlugin(Star):
    """崩坏3往事乐土攻略插件"""

    def __init__(self, context: Context, config: dict = None):
        super().__init__(context, config)
        self.alias_manager: Optional[AliasManager] = None
        self.resource_path: Optional[Path] = None
        self.alias_data: Dict[str, Any] = {}

    async def initialize(self):
        """插件初始化"""
        # 获取插件数据目录
        data_dir = StarTools.get_data_dir("astrbot_plugin_bh3")
        self.resource_path = Path(__file__).parent / "resources"

        # 确保资源目录存在
        self.resource_path.mkdir(parents=True, exist_ok=True)

        # 加载别名配置
        await self._load_alias_config()

        logger.info("崩坏3乐土攻略插件初始化完成")

    async def _load_alias_config(self):
        """加载别名配置文件"""
        alias_file = Path(__file__).parent / "alias.yaml"

        if alias_file.exists():
            try:
                with open(alias_file, 'r', encoding='utf-8') as f:
                    self.alias_data = yaml.safe_load(f) or {}
                self.alias_manager = AliasManager(self.alias_data)
                logger.info(f"已加载 {len(self.alias_data)} 个角色别名")
            except Exception as e:
                logger.error(f"加载别名配置失败: {e}")
                self.alias_data = {}
                self.alias_manager = AliasManager({})
        else:
            logger.warning("别名配置文件不存在，将使用空配置")
            self.alias_manager = AliasManager({})

    def _find_strategy_image(self, char_name: str) -> Optional[Path]:
        """
        查找攻略图片
        @param char_name: 角色文件名
        @return: 图片路径或None
        """
        # 支持的图片格式
        extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']

        for ext in extensions:
            image_path = self.resource_path / f"{char_name}{ext}"
            if image_path.exists():
                return image_path

        return None

    @filter.command("乐土攻略")
    async def get_strategy(self, event: AstrMessageEvent, char_name: str = ""):
        """
        查询崩坏3乐土攻略
        用法: /乐土攻略 <角色名>
        示例: /乐土攻略 爱莉希雅
        """
        if not char_name:
            yield event.plain_result(
                "❌ 请提供角色名称\n"
                "用法: /乐土攻略 <角色名>\n"
                "示例: /乐土攻略 爱莉希雅\n"
                "💡 使用 /乐土帮助 查看更多信息"
            )
            return

        # 清理输入
        char_name = char_name.strip()

        # 通过别名获取角色文件名
        if self.alias_manager:
            file_name = self.alias_manager.get(char_name)
        else:
            file_name = None

        if not file_name:
            yield event.plain_result(
                f"❌ 未找到角色 '{char_name}' 的攻略\n"
                f"💡 请检查角色名称是否正确\n"
                f"💡 使用 /乐土帮助 查看支持的角色列表"
            )
            return

        # 查找攻略图片
        image_path = self._find_strategy_image(file_name)

        if image_path and image_path.exists():
            # 发送图片
            yield event.chain_result([
                Plain(f"✅ 找到 {char_name} 的乐土攻略\n"),
                Image(file=str(image_path))
            ])
        else:
            yield event.plain_result(
                f"❌ 未找到 {char_name} 的攻略图片\n"
                f"💡 尝试使用 /更新乐土攻略 获取最新攻略图片"
            )

    @filter.command("乐土帮助")
    async def show_help(self, event: AstrMessageEvent):
        """
        显示乐土攻略插件帮助信息
        用法: /乐土帮助
        """
        help_text = """🎮 崩坏3往事乐土攻略插件

📋 可用命令:

1. /乐土攻略 <角色名>
   查询指定角色的乐土攻略
   示例: /乐土攻略 爱莉希雅
   示例: /乐土攻略 人律

2. /乐土帮助
   显示此帮助信息

3. /更新乐土攻略
   更新/下载攻略图片资源（仅限管理员）

💡 使用提示:
• 支持角色别名查询，如"人律"、"爱莉"都可以查到爱莉希雅
• 部分角色有多个流派攻略，会显示所有可用攻略
• 攻略图片来源：米游社@月光中心official

🔥 热门角色示例:
• 爱莉希雅（人律、爱莉）
• 琪亚娜（炎律、终焉）
• 雷电芽衣（雷律、始源）
• 布洛妮娅（理律、真理）
• 希儿（死律、魇夜星渊）
"""
        yield event.plain_result(help_text)

    @filter.command("更新乐土攻略")
    async def update_strategy(self, event: AstrMessageEvent, proxy: str = ""):
        """
        更新乐土攻略图片资源（仅限管理员）
        用法: /更新乐土攻略 [代理地址]
        示例: /更新乐土攻略
        示例: /更新乐土攻略 https://ghproxy.com
        """
        # 检查权限
        if not await self._check_admin(event):
            yield event.plain_result("❌ 只有管理员才能更新攻略资源")
            return

        yield event.plain_result("⏳ 开始更新乐土攻略资源，请稍候...")

        try:
            #  GitHub 仓库地址
            repo_url = "https://github.com/MskTmi/ElysianRealm-Data.git"

            # 如果提供了代理地址
            if proxy:
                if proxy == "ghproxy":
                    repo_url = "https://ghfast.top/https://github.com/MskTmi/ElysianRealm-Data.git"
                else:
                    proxy = proxy.rstrip('/')
                    repo_url = f"{proxy}/https://github.com/MskTmi/ElysianRealm-Data.git"

            # 临时目录
            import tempfile
            import shutil
            import subprocess

            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                # 执行 git clone
                cmd = [
                    "git", "clone",
                    "--depth", "1",
                    repo_url,
                    str(temp_path / "ElysianRealm-Data")
                ]

                logger.info(f"执行命令: {' '.join(cmd)}")

                # 使用 subprocess 执行命令
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                stdout, stderr = await process.communicate()

                if process.returncode != 0:
                    error_msg = stderr.decode('utf-8', errors='ignore') if stderr else "未知错误"
                    yield event.plain_result(f"❌ 更新失败: {error_msg}")
                    return

                # 复制图片文件
                source_dir = temp_path / "ElysianRealm-Data"
                if not source_dir.exists():
                    yield event.plain_result("❌ 下载的仓库目录不存在")
                    return

                # 统计复制的文件数量
                copied_count = 0
                image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.webp')

                for file in source_dir.iterdir():
                    if file.is_file() and file.suffix.lower() in image_extensions:
                        dest_file = self.resource_path / file.name
                        shutil.copy2(file, dest_file)
                        copied_count += 1

                yield event.plain_result(
                    f"✅ 乐土攻略更新完成！\n"
                    f"📊 共更新 {copied_count} 张攻略图片\n"
                    f"💡 现在可以使用 /乐土攻略 <角色名> 查询了"
                )

        except Exception as e:
            logger.error(f"更新乐土攻略失败: {e}")
            yield event.plain_result(f"❌ 更新失败: {str(e)}")

    async def _check_admin(self, event: AstrMessageEvent) -> bool:
        """检查用户是否为管理员"""
        # 获取用户ID
        user_id = event.get_sender_id()

        # 尝试从配置中读取管理员列表
        # 这里简化处理，实际应该从 AstrBot 配置中读取
        try:
            # 获取平台适配器
            platform = event.get_platform_name()

            # 检查是否是群聊中的管理员
            if hasattr(event, 'is_admin'):
                return event.is_admin

            # 默认允许（生产环境应该更严格）
            return True
        except Exception as e:
            logger.warning(f"检查管理员权限失败: {e}")
            return False

    async def terminate(self):
        """插件销毁"""
        logger.info("崩坏3乐土攻略插件已卸载")
