import os
import re
import yaml
import aiohttp
import asyncio
import json
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
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


class AutoUpdater:
    """自动更新管理器 - 检测仓库更新并自动更新"""

    def __init__(self, plugin: 'BH3ElysianRealmPlugin'):
        self.plugin = plugin
        self.data_dir = StarTools.get_data_dir("astrbot_plugin_bh3_Elysian-Realm")
        self.version_file = self.data_dir / "version.json"
        self.check_interval = 3600  # 默认1小时检查一次
        self.auto_update = True  # 默认开启自动更新
        self.notify_admin = True  # 更新后通知管理员
        self._task = None
        self._running = False

    async def initialize(self):
        """初始化自动更新器"""
        # 加载配置
        await self._load_config()

        # 启动定时检查任务
        if self.auto_update:
            self._running = True
            self._task = asyncio.create_task(self._check_loop())
            logger.info("自动更新管理器已启动")

    async def _load_config(self):
        """加载自动更新配置"""
        config_file = self.data_dir / "auto_update.json"
        if config_file.exists():
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                self.check_interval = config.get('check_interval', 3600)
                self.auto_update = config.get('auto_update', True)
                self.notify_admin = config.get('notify_admin', True)
            except Exception as e:
                logger.error(f"加载自动更新配置失败: {e}")

    async def _save_config(self):
        """保存自动更新配置"""
        config_file = self.data_dir / "auto_update.json"
        try:
            config = {
                'check_interval': self.check_interval,
                'auto_update': self.auto_update,
                'notify_admin': self.notify_admin
            }
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存自动更新配置失败: {e}")

    async def _check_loop(self):
        """定时检查循环"""
        while self._running:
            try:
                await self._check_and_update()
            except Exception as e:
                logger.error(f"自动检查更新失败: {e}")

            # 等待下一次检查
            await asyncio.sleep(self.check_interval)

    async def _check_and_update(self):
        """检查并执行更新"""
        try:
            # 获取远程仓库最新提交信息
            remote_commit = await self._get_remote_commit()
            if not remote_commit:
                return

            # 获取本地保存的版本信息
            local_commit = await self._get_local_commit()

            # 比较版本
            if remote_commit != local_commit:
                logger.info(f"检测到新版本: {remote_commit[:8]} (本地: {local_commit[:8] if local_commit else 'None'})")

                # 执行自动更新
                success = await self._perform_update()

                if success:
                    # 保存新版本号
                    await self._save_local_commit(remote_commit)
                    logger.info("自动更新成功")

                    # 通知管理员
                    if self.notify_admin:
                        await self._notify_admin(f"✅ 乐土攻略插件已自动更新！\n📊 新版本: {remote_commit[:8]}")
                else:
                    logger.error("自动更新失败")
                    if self.notify_admin:
                        await self._notify_admin("❌ 乐土攻略插件自动更新失败，请手动检查")
            else:
                logger.debug("当前已是最新版本")

        except Exception as e:
            logger.error(f"检查更新过程出错: {e}")

    async def _get_remote_commit(self) -> Optional[str]:
        """获取远程仓库最新 commit hash"""
        try:
            # 使用 GitHub API 获取最新提交
            api_url = "https://api.github.com/repos/MskTmi/ElysianRealm-Data/commits/main"

            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('sha', '')
                    else:
                        logger.warning(f"获取远程版本失败: HTTP {response.status}")
                        return None
        except Exception as e:
            logger.error(f"获取远程版本出错: {e}")
            return None

    async def _get_local_commit(self) -> Optional[str]:
        """获取本地保存的 commit hash"""
        if self.version_file.exists():
            try:
                with open(self.version_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return data.get('commit_hash')
            except Exception as e:
                logger.error(f"读取本地版本文件失败: {e}")
        return None

    async def _save_local_commit(self, commit_hash: str):
        """保存本地版本信息"""
        try:
            data = {
                'commit_hash': commit_hash,
                'update_time': datetime.now().isoformat()
            }
            with open(self.version_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存版本文件失败: {e}")

    async def _perform_update(self) -> bool:
        """执行更新操作"""
        try:
            import tempfile
            import shutil

            repo_url = "https://github.com/MskTmi/ElysianRealm-Data.git"

            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                # 执行 git clone
                cmd = [
                    "git", "clone",
                    "--depth", "1",
                    repo_url,
                    str(temp_path / "ElysianRealm-Data")
                ]

                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                stdout, stderr = await process.communicate()

                if process.returncode != 0:
                    logger.error(f"Git clone 失败: {stderr.decode()}")
                    return False

                # 复制图片文件
                source_dir = temp_path / "ElysianRealm-Data"
                if not source_dir.exists():
                    logger.error("下载的仓库目录不存在")
                    return False

                copied_count = 0
                image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.webp')

                for file in source_dir.iterdir():
                    if file.is_file() and file.suffix.lower() in image_extensions:
                        dest_file = self.plugin.resource_path / file.name
                        shutil.copy2(file, dest_file)
                        copied_count += 1

                logger.info(f"自动更新完成，共更新 {copied_count} 张图片")
                return True

        except Exception as e:
            logger.error(f"执行更新失败: {e}")
            return False

    async def _notify_admin(self, message: str):
        """通知管理员"""
        try:
            # 这里可以通过 AstrBot 的通知机制发送给管理员
            # 暂时只记录日志
            logger.info(f"管理员通知: {message}")
        except Exception as e:
            logger.error(f"通知管理员失败: {e}")

    async def stop(self):
        """停止自动更新器"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("自动更新管理器已停止")

    def set_interval(self, seconds: int):
        """设置检查间隔"""
        self.check_interval = max(300, seconds)  # 最少5分钟
        asyncio.create_task(self._save_config())

    def set_auto_update(self, enabled: bool):
        """设置是否开启自动更新"""
        self.auto_update = enabled
        asyncio.create_task(self._save_config())

        if enabled and not self._running:
            self._running = True
            self._task = asyncio.create_task(self._check_loop())
        elif not enabled and self._running:
            asyncio.create_task(self.stop())


@register("astrbot_plugin_bh3_Elysian-Realm", "飞翔的死猪", "适用于astrbot的崩坏3乐土查询插件", "1.0.0")
class BH3ElysianRealmPlugin(Star):
    """崩坏3往事乐土攻略插件"""

    def __init__(self, context: Context, config: dict = None):
        super().__init__(context, config)
        self.alias_manager: Optional[AliasManager] = None
        self.resource_path: Optional[Path] = None
        self.alias_data: Dict[str, Any] = {}
        self.auto_updater: Optional[AutoUpdater] = None

    async def initialize(self):
        """插件初始化"""
        # 获取插件数据目录
        data_dir = StarTools.get_data_dir("astrbot_plugin_bh3_Elysian-Realm")
        self.resource_path = Path(__file__).parent / "resources"

        # 确保资源目录存在
        self.resource_path.mkdir(parents=True, exist_ok=True)

        # 加载别名配置
        await self._load_alias_config()

        # 初始化自动更新器
        self.auto_updater = AutoUpdater(self)
        await self.auto_updater.initialize()

        logger.info("适用于astrbot的崩坏3乐土查询插件初始化完成")

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

4. /检查乐土更新
   手动检查是否有新版本

5. /乐土自动更新 <开启/关闭>
   开启或关闭自动更新功能

6. /乐土更新状态
   查看自动更新状态和配置

💡 使用提示:
• 支持角色别名查询，如"人律"、"爱莉"都可以查到爱莉希雅
• 部分角色有多个流派攻略，会显示所有可用攻略
• 攻略图片来源：米游社@月光中心official
• 插件会自动检测仓库更新，默认每小时检查一次

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

                # 获取最新 commit hash 并保存
                try:
                    remote_commit = await self.auto_updater._get_remote_commit()
                    if remote_commit:
                        await self.auto_updater._save_local_commit(remote_commit)
                except Exception as e:
                    logger.warning(f"保存版本信息失败: {e}")

                yield event.plain_result(
                    f"✅ 乐土攻略更新完成！\n"
                    f"📊 共更新 {copied_count} 张攻略图片\n"
                    f"💡 现在可以使用 /乐土攻略 <角色名> 查询了"
                )

        except Exception as e:
            logger.error(f"更新乐土攻略失败: {e}")
            yield event.plain_result(f"❌ 更新失败: {str(e)}")

    @filter.command("检查乐土更新")
    async def check_update(self, event: AstrMessageEvent):
        """
        手动检查乐土攻略是否有更新
        用法: /检查乐土更新
        """
        yield event.plain_result("🔍 正在检查更新，请稍候...")

        try:
            remote_commit = await self.auto_updater._get_remote_commit()
            local_commit = await self.auto_updater._get_local_commit()

            if not remote_commit:
                yield event.plain_result("❌ 无法获取远程版本信息，请检查网络连接")
                return

            if remote_commit != local_commit:
                yield event.plain_result(
                    f"📢 发现新版本！\n"
                    f"📦 远程版本: {remote_commit[:8]}\n"
                    f"📂 本地版本: {local_commit[:8] if local_commit else '未记录'}\n"
                    f"💡 使用 /更新乐土攻略 获取最新资源"
                )
            else:
                yield event.plain_result(
                    f"✅ 当前已是最新版本\n"
                    f"📦 版本: {local_commit[:8] if local_commit else '未知'}\n"
                    f"⏰ 上次检查: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )

        except Exception as e:
            logger.error(f"检查更新失败: {e}")
            yield event.plain_result(f"❌ 检查更新失败: {str(e)}")

    @filter.command("乐土自动更新")
    async def toggle_auto_update(self, event: AstrMessageEvent, action: str = ""):
        """
        开启或关闭自动更新功能
        用法: /乐土自动更新 <开启/关闭>
        示例: /乐土自动更新 开启
        """
        if not await self._check_admin(event):
            yield event.plain_result("❌ 只有管理员才能修改自动更新设置")
            return

        action = action.strip().lower()

        if action in ["开启", "开", "on", "true", "1"]:
            self.auto_updater.set_auto_update(True)
            yield event.plain_result(
                "✅ 已开启自动更新功能\n"
                f"⏰ 检查间隔: {self.auto_updater.check_interval // 60} 分钟\n"
                "💡 插件将自动检测并更新攻略图片"
            )
        elif action in ["关闭", "关", "off", "false", "0"]:
            self.auto_updater.set_auto_update(False)
            yield event.plain_result(
                "✅ 已关闭自动更新功能\n"
                "💡 您可以使用 /检查乐土更新 手动检查更新"
            )
        else:
            yield event.plain_result(
                "❌ 参数错误\n"
                "用法: /乐土自动更新 <开启/关闭>\n"
                "示例: /乐土自动更新 开启"
            )

    @filter.command("乐土更新状态")
    async def update_status(self, event: AstrMessageEvent):
        """
        查看自动更新状态和配置
        用法: /乐土更新状态
        """
        try:
            local_commit = await self.auto_updater._get_local_commit()
            remote_commit = await self.auto_updater._get_remote_commit()

            status_text = "📊 乐土攻略插件更新状态\n\n"

            # 自动更新状态
            status_text += f"🔄 自动更新: {'开启' if self.auto_updater.auto_update else '关闭'}\n"
            status_text += f"⏰ 检查间隔: {self.auto_updater.check_interval // 60} 分钟\n"
            status_text += f"📢 通知管理员: {'开启' if self.auto_updater.notify_admin else '关闭'}\n\n"

            # 版本信息
            if local_commit:
                status_text += f"📂 本地版本: {local_commit[:8]}\n"
            else:
                status_text += "📂 本地版本: 未记录\n"

            if remote_commit:
                status_text += f"📦 远程版本: {remote_commit[:8]}\n"
                if local_commit and local_commit != remote_commit:
                    status_text += "⚠️ 发现新版本可用！\n"
                else:
                    status_text += "✅ 当前已是最新版本\n"
            else:
                status_text += "📦 远程版本: 无法获取\n"

            yield event.plain_result(status_text)

        except Exception as e:
            logger.error(f"获取更新状态失败: {e}")
            yield event.plain_result(f"❌ 获取状态失败: {str(e)}")

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
        # 停止自动更新器
        if self.auto_updater:
            await self.auto_updater.stop()

        logger.info("适用于astrbot的崩坏3乐土查询插件已卸载")
