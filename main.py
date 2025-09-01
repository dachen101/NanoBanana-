import sys
import json
import logging
import aiohttp
import asyncio
import re
import pandas as pd
import os
import time
import base64
import shutil
import ssl
from pathlib import Path
import concurrent.futures
from functools import partial
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLabel, QLineEdit, QSpinBox, QPushButton,
                            QFileDialog, QListWidget, QTableWidget, QTableWidgetItem, 
                            QHeaderView, QDialog, QTextEdit, QComboBox, QCheckBox, QListWidgetItem,
                            QTreeWidget, QTreeWidgetItem, QMenu, QInputDialog, QMessageBox,
                            QSplitter, QPlainTextEdit, QGroupBox, QGridLayout, QScrollArea,
                            QFrame, QProgressBar, QTabWidget, QAbstractItemView, QStyledItemDelegate, QStyle)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer, QSize
from PyQt6.QtGui import QPixmap, QImage, QFont, QPalette, QColor, QIcon, QTextOption

# 导入声音播放模块
try:
    import winsound  # Windows系统声音
except ImportError:
    winsound = None

try:
    import subprocess  # 跨平台声音播放
except ImportError:
    subprocess = None

def get_app_path():
    """获取应用程序路径，支持打包后的exe"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    else:
        return Path(__file__).parent

APP_PATH = get_app_path()
IMAGES_PATH = APP_PATH / 'images'

def setup_ssl_context():
    """设置SSL上下文，解决证书验证问题"""
    try:
        # 创建SSL上下文
        ssl_context = ssl.create_default_context()
        
        # 针对macOS系统的特殊处理
        if sys.platform == "darwin":  # macOS
            try:
                # 尝试加载系统证书
                import certifi
                ssl_context.load_verify_locations(certifi.where())
                logging.info("已加载macOS系统证书")
            except ImportError:
                logging.info("certifi库未安装，跳过证书加载")
        
        # 为了兼容性，禁用主机名检查和证书验证
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        logging.info("SSL上下文已配置 (跳过证书验证)")
        return ssl_context
        
    except Exception as e:
        logging.warning(f"SSL配置失败，将完全禁用SSL验证: {e}")
        return False

def ensure_images_directory():
    """确保images目录存在"""
    if not IMAGES_PATH.exists():
        IMAGES_PATH.mkdir(parents=True, exist_ok=True)
        logging.info(f"创建图片目录: {IMAGES_PATH}")

def create_category_directory(category_name):
    """创建分类目录"""
    ensure_images_directory()
    category_path = IMAGES_PATH / category_name
    if not category_path.exists():
        category_path.mkdir(parents=True, exist_ok=True)
        logging.info(f"创建分类目录: {category_path}")
    return category_path

def rename_category_directory(old_name, new_name):
    """重命名分类目录"""
    ensure_images_directory()
    old_path = IMAGES_PATH / old_name
    new_path = IMAGES_PATH / new_name
    
    if old_path.exists() and not new_path.exists():
        old_path.rename(new_path)
        logging.info(f"重命名分类目录: {old_path} -> {new_path}")
    elif not old_path.exists():
        # 如果旧目录不存在，创建新目录
        create_category_directory(new_name)

def delete_category_directory(category_name):
    """删除分类目录及其所有内容"""
    ensure_images_directory()
    category_path = IMAGES_PATH / category_name
    if category_path.exists():
        shutil.rmtree(category_path)
        logging.info(f"删除分类目录: {category_path}")

def copy_image_to_category(source_path, category_name, image_name):
    """复制图片到分类目录"""
    category_path = create_category_directory(category_name)
    
    # 获取文件扩展名
    source_ext = Path(source_path).suffix
    if not source_ext:
        source_ext = '.png'  # 默认扩展名
    
    # 构建目标文件路径
    target_filename = f"{image_name}{source_ext}"
    target_path = category_path / target_filename
    
    # 复制文件
    shutil.copy2(source_path, target_path)
    logging.info(f"复制图片: {source_path} -> {target_path}")
    
    # 返回相对路径
    return f"images/{category_name}/{target_filename}"

def image_to_base64(image_path):
    """将图片文件转换为base64编码"""
    try:
        with open(image_path, 'rb') as image_file:
            encoded = base64.b64encode(image_file.read()).decode('utf-8')
            # 根据文件扩展名确定MIME类型
            ext = Path(image_path).suffix.lower()
            if ext in ['.jpg', '.jpeg']:
                mime_type = 'image/jpeg'
            elif ext == '.png':
                mime_type = 'image/png'
            elif ext == '.gif':
                mime_type = 'image/gif'
            elif ext == '.webp':
                mime_type = 'image/webp'
            else:
                mime_type = 'image/png'  # 默认
            
            return f"data:{mime_type};base64,{encoded}"
    except Exception as e:
        logging.error(f"转换图片为base64失败: {e}")
        return None

def save_base64_image(base64_data, save_path, filename):
    """将base64编码的图片保存为文件"""
    try:
        # 解析base64数据格式 data:image/png;base64,iVBORw0KGgoAAAA...
        if ',' in base64_data:
            header, data = base64_data.split(',', 1)
            # 从header中提取文件类型
            if 'image/jpeg' in header or 'image/jpg' in header:
                ext = '.jpg'
            elif 'image/png' in header:
                ext = '.png'
            elif 'image/gif' in header:
                ext = '.gif'
            elif 'image/webp' in header:
                ext = '.webp'
            else:
                ext = '.png'  # 默认使用png
        else:
            # 如果没有header，直接使用data部分，默认png格式
            data = base64_data
            ext = '.png'
        
        # 确保保存目录存在
        os.makedirs(save_path, exist_ok=True)
        
        # 构建完整的文件路径，处理重名文件
        base_filename = filename
        if not base_filename.endswith(ext):
            base_filename = f"{filename}{ext}"
        
        file_path = Path(save_path) / base_filename
        counter = 1
        
        # 如果文件已存在，添加序号后缀
        while file_path.exists():
            name_part = filename
            new_filename = f"{name_part}-{counter}{ext}"
            file_path = Path(save_path) / new_filename
            counter += 1
        
        # 解码并保存图片
        image_data = base64.b64decode(data)
        with open(file_path, 'wb') as f:
            f.write(image_data)
        
        logging.info(f"成功保存base64图片: {file_path}")
        return str(file_path)
        
    except Exception as e:
        logging.error(f"保存base64图片失败: {e}")
        return None

# 配置日志
logging.basicConfig(
    filename=APP_PATH / 'nanobana_generator.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

class WorkerSignals(QObject):
    finished = pyqtSignal(str, str, str)  # 提示词, 图片URL, 编号
    error = pyqtSignal(str, str)     # 提示词, 错误信息
    progress = pyqtSignal(str, str)  # 提示词, 状态信息

class AsyncWorker:
    """异步Worker类，使用协程替代线程"""
    def __init__(self, prompt, api_key, image_data=None, api_platform="云雾", retry_count=3, number=None, signals=None):
        self.prompt = prompt
        self.api_key = api_key
        self.image_data = image_data or []  # 现在包含{'name': '', 'url': '', 'path': ''} 的数据
        self.api_platform = api_platform
        self.retry_count = retry_count
        self.number = number
        self.signals = signals  # 从外部传入信号对象
        
    async def run(self):
        try:
            # 发送进度信号
            self.signals.progress.emit(self.prompt, "生成中...")
            
            # 验证API密钥
            if not self.api_key:
                raise ValueError("API密钥不能为空")
                
            # 构建API请求
            if self.api_platform == "云雾":
                api_url = "https://yunwu.ai/v1/chat/completions"
            elif self.api_platform == "apicore":
                api_url = "https://api.apicore.ai/v1/chat/completions"
            else:  # API易
                api_url = "https://vip.apiyi.com/v1/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            
            # 构建消息内容
            content = [{"type": "text", "text": self.prompt}]
            
            # 记录图片路径信息用于日志
            image_path_info = []
            
            # 添加图片（支持URL和本地文件）
            for img_data in self.image_data:
                if 'path' in img_data and img_data['path']:
                    # 本地图片，转换为base64
                    local_path = APP_PATH / img_data['path']
                    if local_path.exists():
                        base64_url = image_to_base64(local_path)
                        if base64_url:
                            content.append({
                                "type": "image_url",
                                "image_url": {"url": base64_url}
                            })
                            # 记录路径信息用于日志
                            image_path_info.append(f"本地图片: {img_data['name']} -> {img_data['path']}")
                            logging.info(f"添加本地图片: {img_data['name']} -> {img_data['path']}")
                        else:
                            logging.warning(f"本地图片转换base64失败: {img_data['path']}")
                    else:
                        logging.warning(f"本地图片文件不存在: {img_data['path']}")
                elif 'url' in img_data and img_data['url']:
                    # 网络图片，使用URL
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": img_data['url']}
                    })
                    # 记录URL信息用于日志
                    image_path_info.append(f"网络图片: {img_data['name']} -> {img_data['url']}")
                    logging.info(f"添加网络图片: {img_data['name']} -> {img_data['url']}")
            
            # 根据API平台选择模型
            if self.api_platform == "apicore":
                model_name = "gemini-2.5-flash-image"
            else:
                model_name = "gemini-2.5-flash-image-preview"
            
            payload = {
                "model": model_name,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a helpful assistant."
                    },
                    {
                        "role": "user",
                        "content": content
                    }
                ]
            }
            
            # 记录请求信息
            logging.info("发送API请求:")
            logging.info(f"URL: {api_url}")
            
            # 创建用于日志记录的payload副本，替换BASE64图片数据为路径信息
            log_payload = payload.copy()
            if 'messages' in log_payload:
                log_messages = []
                for msg in log_payload['messages']:
                    log_msg = msg.copy()
                    if 'content' in msg and isinstance(msg['content'], list):
                        log_content = []
                        image_index = 0  # 图片索引计数器
                        for item in msg['content']:
                            if item.get('type') == 'image_url' and 'image_url' in item:
                                # 替换BASE64数据为实际路径信息
                                if image_index < len(image_path_info):
                                    path_info = image_path_info[image_index]
                                    log_item = {
                                        "type": "image_url",
                                        "image_url": {"url": f"[{path_info}]"}
                                    }
                                else:
                                    log_item = {
                                        "type": "image_url",
                                        "image_url": {"url": "[图片路径信息缺失]"}
                                    }
                                log_content.append(log_item)
                                image_index += 1
                            else:
                                log_content.append(item)
                        log_msg['content'] = log_content
                    log_messages.append(log_msg)
                log_payload['messages'] = log_messages
            
            logging.info(f"请求参数: {json.dumps(log_payload, ensure_ascii=False, indent=2)}")
            
            # 发送异步请求(带重试机制)
            retry_times = 0
            while retry_times <= self.retry_count:
                try:
                    # 添加随机延迟，避免同时发送大量请求
                    import random
                    await asyncio.sleep(random.uniform(0.1, 0.5))  # 异步延迟，时间缩短
                    
                    # 使用aiohttp发送异步请求
                    timeout = aiohttp.ClientTimeout(total=600)
                    
                    # 使用统一的SSL配置
                    ssl_context = setup_ssl_context()
                    connector = aiohttp.TCPConnector(ssl=ssl_context)
                    
                    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                        async with session.post(
                            api_url, 
                            headers=headers, 
                            json=payload
                        ) as response:
                            # 记录响应信息
                            logging.info(f"API响应状态码: {response.status}")
                            response_text = await response.text()
                            logging.info(f"API响应内容: {response_text}")
                            
                            response.raise_for_status()
                            data = await response.json()
                            
                            # 从返回的markdown中提取图片URL或base64数据
                            content = data["choices"][0]["message"]["content"]
                            
                            # 首先尝试匹配base64格式的图片 (nano banana模型的新格式)
                            base64_match = re.search(r'!\[.*?\]\((data:image/[^;]+;base64,[^)]+)\)', content)
                            if base64_match:
                                base64_data = base64_match.group(1)
                                logging.info(f"成功提取base64图片数据，长度: {len(base64_data)}")
                                
                                # 读取配置中的保存路径
                                try:
                                    config_path = APP_PATH / 'config.json'
                                    with open(config_path, 'r', encoding='utf-8') as f:
                                        config_data = json.load(f)
                                    save_path = config_data.get('save_path', str(APP_PATH / 'generated_images'))
                                except Exception as e:
                                    logging.warning(f"读取配置失败，使用默认路径: {e}")
                                    save_path = str(APP_PATH / 'generated_images')
                                
                                # 生成文件名
                                filename = self.number or f"image_{int(time.time())}"
                                
                                # 保存base64图片
                                saved_path = save_base64_image(base64_data, save_path, filename)
                                if saved_path:
                                    logging.info(f"成功保存图片: {saved_path}")
                                    self.signals.finished.emit(self.prompt, saved_path, self.number or "")
                                    return
                                else:
                                    error_msg = "保存base64图片失败"
                                    logging.error(error_msg)
                                    raise ValueError(error_msg)
                            
                            # 如果没有base64格式，尝试传统的图片URL格式
                            # 支持多种格式：![image](URL)、![图片](URL)、[点击下载](URL)
                            image_url_match = re.search(r'!\[.*?\]\((.*?)\)', content)
                            if not image_url_match:
                                image_url_match = re.search(r'\[点击下载\]\((.*?)\)', content)
                            
                            if image_url_match:
                                image_url = image_url_match.group(1)
                                logging.info(f"成功提取图片URL: {image_url}")
                                self.signals.finished.emit(self.prompt, image_url, self.number or "")
                                return
                            else:
                                error_msg = "响应中没有找到图片URL或base64数据"
                                logging.error(error_msg)
                                raise ValueError(error_msg)
                        
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                    retry_times += 1
                    if retry_times <= self.retry_count:
                        logging.warning(f"请求失败,正在进行第{retry_times}次重试: {str(e)}")
                        self.signals.progress.emit(self.prompt, f"重试中 ({retry_times}/{self.retry_count})...")
                        await asyncio.sleep(1)  # 异步延迟
                        continue
                    else:
                        error_msg = f"请求失败(已重试{self.retry_count}次): {str(e)}"
                        logging.error(error_msg)
                        self.signals.error.emit(self.prompt, error_msg)
                        return
                        
        except Exception as e:
            error_msg = f"发生错误: {str(e)}"
            logging.error(error_msg)
            self.signals.error.emit(self.prompt, error_msg)

class KeyEditDialog(QDialog):
    """密钥编辑对话框"""
    
    def __init__(self, parent=None, key_data=None):
        super().__init__(parent)
        self.setWindowTitle("🔑 密钥编辑" if key_data else "🔑 新建密钥")
        self.resize(400, 300)
        self.setModal(True)
        
        self.key_data = key_data.copy() if key_data else None
        self.setup_ui()
        
        if self.key_data:
            self.load_key_data()
    
    def setup_ui(self):
        """设置UI界面"""
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 密钥名称
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("密钥名称:"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("请输入容易识别的名称，如：我的云雾密钥")
        name_layout.addWidget(self.name_input)
        layout.addLayout(name_layout)
        
        # API平台
        platform_layout = QHBoxLayout()
        platform_layout.addWidget(QLabel("API平台:"))
        self.platform_combo = QComboBox()
        self.platform_combo.addItems(["云雾", "API易", "apicore"])
        platform_layout.addWidget(self.platform_combo)
        layout.addLayout(platform_layout)
        
        # API密钥
        key_layout = QVBoxLayout()
        key_layout.addWidget(QLabel("API密钥:"))
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("请输入完整的API密钥...")
        key_layout.addWidget(self.key_input)
        
        # 显示/隐藏密钥按钮
        key_toggle_layout = QHBoxLayout()
        key_toggle_layout.addStretch()
        self.show_key_checkbox = QCheckBox("显示密钥")
        self.show_key_checkbox.toggled.connect(self.toggle_key_visibility)
        key_toggle_layout.addWidget(self.show_key_checkbox)
        key_layout.addLayout(key_toggle_layout)
        
        layout.addLayout(key_layout)
        
        # 提示信息
        tips_label = QLabel("""
<b>提示:</b><br>
• 密钥名称用于在基础配置中快速识别和选择<br>
• 请确保API密钥的有效性和平台匹配<br>
• 密钥信息会加密保存在本地配置文件中
        """)
        tips_label.setWordWrap(True)
        tips_label.setStyleSheet("color: #666; background-color: #f8f9fa; padding: 10px; border-radius: 6px; font-size: 12px;")
        layout.addWidget(tips_label)
        
        layout.addStretch()
        
        # 底部按钮
        button_layout = QHBoxLayout()
        
        self.save_button = QPushButton("✅ 保存")
        self.cancel_button = QPushButton("❌ 取消")
        
        self.save_button.clicked.connect(self.save_key)
        self.cancel_button.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
        
        # 设置默认按钮
        self.save_button.setDefault(True)
        
        # 默认隐藏密钥
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
    
    def toggle_key_visibility(self, checked):
        """切换密钥显示/隐藏"""
        if checked:
            self.key_input.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
    
    def load_key_data(self):
        """加载已有密钥数据"""
        self.name_input.setText(self.key_data['name'])
        self.platform_combo.setCurrentText(self.key_data['platform'])
        self.key_input.setText(self.key_data['api_key'])
    
    def save_key(self):
        """保存密钥"""
        # 验证输入
        name = self.name_input.text().strip()
        platform = self.platform_combo.currentText()
        api_key = self.key_input.text().strip()
        
        if not name:
            QMessageBox.warning(self, "提示", "请输入密钥名称")
            self.name_input.setFocus()
            return
        
        if not api_key:
            QMessageBox.warning(self, "提示", "请输入API密钥")
            self.key_input.setFocus()
            return
        
        # 检查名称是否重复（编辑时排除自己）
        parent_dialog = self.parent()
        if hasattr(parent_dialog, 'key_library'):
            existing_names = set(parent_dialog.key_library.keys())
            if self.key_data:  # 编辑模式，排除自己的原名称
                existing_names.discard(self.key_data['name'])
            
            if name in existing_names:
                QMessageBox.warning(self, "提示", f"密钥名称 '{name}' 已存在，请使用其他名称")
                self.name_input.setFocus()
                return
        
        # 构建密钥数据
        current_time = time.strftime('%Y-%m-%d %H:%M:%S')
        self.result_key_data = {
            'name': name,
            'api_key': api_key,
            'platform': platform,
            'created_time': self.key_data.get('created_time', current_time) if self.key_data else current_time,
            'last_used': self.key_data.get('last_used', '从未使用') if self.key_data else '从未使用'
        }
        
        self.accept()
    
    def get_key_data(self):
        """获取密钥数据"""
        return getattr(self, 'result_key_data', {})

class SettingsDialog(QDialog):
    """统一设置管理对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙️ 设置管理中心")
        self.resize(1100, 750)
        self.setMinimumSize(900, 650)
        
        # 从父窗口获取数据
        if parent:
            self.api_key = parent.api_key
            self.api_platform = parent.api_platform
            self.thread_count = parent.thread_count
            self.retry_count = parent.retry_count
            self.save_path = parent.save_path
            self.style_library = parent.style_library.copy()
            self.category_links = parent.category_links.copy()
            self.current_style = parent.current_style
            self.custom_style_content = parent.custom_style_content
            self.key_library = parent.key_library.copy()
            self.current_key_name = parent.current_key_name
        else:
            self.api_key = ""
            self.api_platform = "云雾"
            self.thread_count = 5
            self.retry_count = 3
            self.save_path = ""
            self.style_library = {}
            self.category_links = {}
            self.current_style = ""
            self.custom_style_content = ""
            self.key_library = {}
            self.current_key_name = ""
        
        self.setup_ui()
        self.load_settings()
        
    def setup_ui(self):
        """设置UI界面"""
        layout = QVBoxLayout(self)
        
        # 创建标签页
        self.tab_widget = QTabWidget()
        
        # 基础配置标签页
        self.create_config_tab()
        
        # 密钥库管理标签页（放在基础配置右边）
        self.create_key_tab()
        
        # 风格库管理标签页
        self.create_style_tab()
        
        # 参考图管理标签页
        self.create_image_tab()
        
        layout.addWidget(self.tab_widget)
        
        # 底部按钮
        button_layout = QHBoxLayout()
        
        self.ok_button = QPushButton("✅ 确定")
        self.ok_button.clicked.connect(self.accept_settings)
        
        self.cancel_button = QPushButton("❌ 取消")
        self.cancel_button.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
        
        # 设置现代化样式
        self.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #ddd;
                border-radius: 8px;
                background-color: white;
            }
            
            QTabWidget::tab-bar {
                alignment: left;
            }
            
            QTabBar::tab {
                background-color: #f0f0f0;
                padding: 12px 20px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-weight: 500;
            }
            
            QTabBar::tab:selected {
                background-color: white;
                border-bottom: 2px solid #1976d2;
                color: #1976d2;
            }
            
            QTabBar::tab:hover {
                background-color: #e3f2fd;
            }
        """)
    
    def create_config_tab(self):
        """创建基础配置标签页"""
        config_widget = QWidget()
        layout = QVBoxLayout(config_widget)
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 密钥选择区域
        key_select_group = QGroupBox("🔑 密钥选择")
        key_select_layout = QGridLayout(key_select_group)
        
        key_select_layout.addWidget(QLabel("选择密钥:"), 0, 0)
        self.key_selector_combo = QComboBox()
        self.key_selector_combo.setMinimumWidth(300)
        self.key_selector_combo.addItem("请先在密钥库中添加密钥...")
        self.key_selector_combo.currentTextChanged.connect(self.on_key_selected)
        key_select_layout.addWidget(self.key_selector_combo, 0, 1)
        
        # 当前密钥信息显示
        key_select_layout.addWidget(QLabel("当前平台:"), 1, 0)
        self.current_platform_label = QLabel("--")
        self.current_platform_label.setStyleSheet("font-weight: bold; color: #1976d2;")
        key_select_layout.addWidget(self.current_platform_label, 1, 1)
        
        key_select_layout.addWidget(QLabel("最后使用:"), 2, 0)
        self.current_last_used_label = QLabel("--")
        self.current_last_used_label.setStyleSheet("color: #666;")
        key_select_layout.addWidget(self.current_last_used_label, 2, 1)
        
        # 提示信息
        tips_label = QLabel("💡 请在「密钥库」标签页中添加和管理您的API密钥")
        tips_label.setStyleSheet("color: #666; font-style: italic; margin-top: 10px;")
        key_select_layout.addWidget(tips_label, 3, 0, 1, 2)
        
        layout.addWidget(key_select_group)
        
        # 生成参数区域
        params_group = QGroupBox("⚡ 生成参数")
        params_layout = QGridLayout(params_group)
        
        params_layout.addWidget(QLabel("并发线程数:"), 0, 0)
        self.thread_spin = QSpinBox()
        self.thread_spin.setRange(1, 2000)
        self.thread_spin.setSuffix(" 个")
        params_layout.addWidget(self.thread_spin, 0, 1)
        
        params_layout.addWidget(QLabel("失败重试次数:"), 0, 2)
        self.retry_spin = QSpinBox()
        self.retry_spin.setRange(0, 5)
        self.retry_spin.setSuffix(" 次")
        params_layout.addWidget(self.retry_spin, 0, 3)
        

        
        layout.addWidget(params_group)
        
        # 保存路径区域
        path_group = QGroupBox("📁 保存设置")
        path_layout = QHBoxLayout(path_group)
        
        path_layout.addWidget(QLabel("保存路径:"))
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("选择图片保存路径...")
        path_layout.addWidget(self.path_input)
        
        self.path_button = QPushButton("📁 浏览")
        self.path_button.clicked.connect(self.select_save_path)
        path_layout.addWidget(self.path_button)
        
        layout.addWidget(path_group)
        
        # 使用提示
        tips_group = QGroupBox("💡 使用提示")
        tips_layout = QVBoxLayout(tips_group)
        
        tips_text = QLabel("""
<b>API配置提示:</b><br>
• 请确保API密钥有效且有足够额度<br>
• 不同平台的API调用限制可能不同<br><br>

<b>性能优化建议:</b><br>
• 线程数建议根据API平台限制设置（通常1-50个）<br>
• 过多线程可能导致API限流<br>
• 重试次数建议设置2-3次
        """)
        tips_text.setWordWrap(True)
        tips_text.setStyleSheet("color: #666; background-color: #f8f9fa; padding: 15px; border-radius: 6px;")
        tips_layout.addWidget(tips_text)
        
        layout.addWidget(tips_group)
        layout.addStretch()
        
        self.tab_widget.addTab(config_widget, "⚙️ 基础配置")
    
    def create_style_tab(self):
        """创建风格库管理标签页"""
        style_widget = QWidget()
        layout = QVBoxLayout(style_widget)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 顶部操作区域
        top_layout = QHBoxLayout()
        
        # 风格选择
        top_layout.addWidget(QLabel("当前风格:"))
        self.style_combo = QComboBox()
        self.style_combo.setMinimumWidth(200)
        self.style_combo.addItem("选择风格...")
        self.style_combo.currentTextChanged.connect(self.on_style_changed)
        top_layout.addWidget(self.style_combo)
        
        top_layout.addStretch()
        
        # 快速操作按钮
        self.new_style_button = QPushButton("➕ 新建")
        self.copy_style_button = QPushButton("📋 复制")
        self.delete_style_button = QPushButton("🗑️ 删除")
        
        self.new_style_button.clicked.connect(self.new_style)
        self.copy_style_button.clicked.connect(self.copy_style)
        self.delete_style_button.clicked.connect(self.delete_style)
        
        top_layout.addWidget(self.new_style_button)
        top_layout.addWidget(self.copy_style_button)
        top_layout.addWidget(self.delete_style_button)
        
        layout.addLayout(top_layout)
        
        # 主要内容区域
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧：风格列表
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        left_layout.addWidget(QLabel("风格列表"))
        self.style_list = QListWidget()
        self.style_list.setMinimumWidth(220)
        self.style_list.currentItemChanged.connect(self.on_style_list_changed)
        left_layout.addWidget(self.style_list)
        
        # 导入导出按钮
        io_layout = QHBoxLayout()
        self.import_style_button = QPushButton("📁 导入")
        self.export_style_button = QPushButton("📤 导出")
        self.reset_style_button = QPushButton("🔄 重置")
        
        self.import_style_button.clicked.connect(self.import_styles)
        self.export_style_button.clicked.connect(self.export_styles)
        self.reset_style_button.clicked.connect(self.reset_default_styles)
        
        io_layout.addWidget(self.import_style_button)
        io_layout.addWidget(self.export_style_button)
        io_layout.addWidget(self.reset_style_button)
        left_layout.addLayout(io_layout)
        
        # 右侧：风格编辑
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        
        # 风格名称
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("风格名称:"))
        self.style_name_input = QLineEdit()
        self.style_name_input.setPlaceholderText("请输入风格名称...")
        name_layout.addWidget(self.style_name_input)
        right_layout.addLayout(name_layout)
        
        # 风格内容
        right_layout.addWidget(QLabel("风格内容:"))
        self.style_content_edit = QPlainTextEdit()
        self.style_content_edit.setPlaceholderText("请输入风格描述内容...\n\n例如：\n极致的超写实主义照片风格，画面呈现出顶级数码单反相机的拍摄效果...")
        right_layout.addWidget(self.style_content_edit)
        
        # 字符计数和保存按钮
        bottom_layout = QHBoxLayout()
        self.style_char_count = QLabel("字符数: 0")
        self.style_char_count.setStyleSheet("color: #666;")
        bottom_layout.addWidget(self.style_char_count)
        
        bottom_layout.addStretch()
        
        self.save_style_button = QPushButton("💾 保存风格")
        self.save_style_button.clicked.connect(self.save_current_style)
        bottom_layout.addWidget(self.save_style_button)
        
        right_layout.addLayout(bottom_layout)
        
        # 添加到分割器
        main_splitter.addWidget(left_widget)
        main_splitter.addWidget(right_widget)
        main_splitter.setSizes([250, 550])
        
        layout.addWidget(main_splitter)
        
        # 绑定文本变化事件
        self.style_name_input.textChanged.connect(self.update_style_char_count)
        self.style_content_edit.textChanged.connect(self.update_style_char_count)
        self.style_content_edit.textChanged.connect(self.on_style_content_changed)
        
        self.current_style_name = ""
        self.tab_widget.addTab(style_widget, "🎨 风格库")
    
    def create_image_tab(self):
        """创建参考图管理标签页"""
        image_widget = QWidget()
        layout = QVBoxLayout(image_widget)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 顶部操作区域
        top_layout = QHBoxLayout()
        
        top_layout.addWidget(QLabel("分类管理:"))
        
        self.new_category_button = QPushButton("➕ 新建分类")
        self.rename_category_button = QPushButton("📝 重命名")
        self.delete_category_button = QPushButton("🗑️ 删除分类")
        
        self.new_category_button.clicked.connect(self.new_category)
        self.rename_category_button.clicked.connect(self.rename_category)
        self.delete_category_button.clicked.connect(self.delete_category)
        
        top_layout.addWidget(self.new_category_button)
        top_layout.addWidget(self.rename_category_button)
        top_layout.addWidget(self.delete_category_button)
        top_layout.addStretch()
        
        layout.addLayout(top_layout)
        
        # 主要内容区域
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧：分类列表
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        left_layout.addWidget(QLabel("图片分类"))
        self.category_list = QListWidget()
        self.category_list.setMinimumWidth(200)
        self.category_list.currentItemChanged.connect(self.on_category_changed)
        left_layout.addWidget(self.category_list)
        
        # 右侧：图片管理
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        
        # 图片操作按钮
        image_buttons_layout = QHBoxLayout()
        image_buttons_layout.addWidget(QLabel("图片管理:"))
        
        self.add_image_button = QPushButton("➕ 添加图片")
        self.delete_image_button = QPushButton("🗑️ 删除选中")
        
        self.add_image_button.clicked.connect(self.add_image)
        self.delete_image_button.clicked.connect(self.delete_image)
        
        image_buttons_layout.addWidget(self.add_image_button)
        image_buttons_layout.addWidget(self.delete_image_button)
        image_buttons_layout.addStretch()
        
        right_layout.addLayout(image_buttons_layout)
        
        # 图片列表表格
        self.image_table = QTableWidget()
        self.image_table.setColumnCount(2)
        self.image_table.setHorizontalHeaderLabels(["图片名称", "路径/链接"])
        self.image_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.image_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.image_table.cellChanged.connect(self.on_image_changed)
        self.image_table.cellDoubleClicked.connect(self.on_image_table_double_clicked)
        right_layout.addWidget(self.image_table)
        
        # 使用说明
        tips_layout = QVBoxLayout()
        tips_label = QLabel("""
<b>使用说明:</b><br>
• 点击"添加图片"选择本地图片文件，系统会自动复制到项目目录<br>
• <b>图片名称在全局范围内必须唯一</b>，不允许在不同分类中有重复名称<br>
• 在提示词中包含图片名称，系统会自动添加对应的参考图<br>
• 建议每个提示词最多包含3-4张参考图<br>
• 支持本地图片（优先）和网络图片链接（兼容旧版本）
        """)
        tips_label.setWordWrap(True)
        tips_label.setStyleSheet("color: #666; background-color: #f8f9fa; padding: 10px; border-radius: 6px; font-size: 12px;")
        tips_layout.addWidget(tips_label)
        
        right_layout.addLayout(tips_layout)
        
        # 添加到分割器
        main_splitter.addWidget(left_widget)
        main_splitter.addWidget(right_widget)
        main_splitter.setSizes([200, 600])
        
        layout.addWidget(main_splitter)
        
        self.current_category = ""
        self.tab_widget.addTab(image_widget, "🖼️ 参考图库")
    
    def create_key_tab(self):
        """创建密钥库管理标签页"""
        key_widget = QWidget()
        layout = QVBoxLayout(key_widget)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 顶部操作区域
        top_layout = QHBoxLayout()
        
        top_layout.addWidget(QLabel("密钥管理:"))
        
        self.new_key_button = QPushButton("➕ 新建密钥")
        self.edit_key_button = QPushButton("📝 编辑密钥")
        self.delete_key_button = QPushButton("🗑️ 删除密钥")
        
        self.new_key_button.clicked.connect(self.new_key)
        self.edit_key_button.clicked.connect(self.edit_key)
        self.delete_key_button.clicked.connect(self.delete_key)
        
        top_layout.addWidget(self.new_key_button)
        top_layout.addWidget(self.edit_key_button)
        top_layout.addWidget(self.delete_key_button)
        top_layout.addStretch()
        
        layout.addLayout(top_layout)
        
        # 主要内容区域
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧：密钥列表
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        left_layout.addWidget(QLabel("密钥列表"))
        self.key_list = QListWidget()
        self.key_list.setMinimumWidth(220)
        self.key_list.currentItemChanged.connect(self.on_key_changed)
        left_layout.addWidget(self.key_list)
        
        # 右侧：密钥详情
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        
        # 密钥详情标题
        right_layout.addWidget(QLabel("密钥详情"))
        
        # 详情显示区域
        self.key_details_widget = QWidget()
        details_layout = QGridLayout(self.key_details_widget)
        
        # 密钥名称
        details_layout.addWidget(QLabel("名称:"), 0, 0)
        self.key_detail_name = QLabel("--")
        self.key_detail_name.setStyleSheet("font-weight: bold; color: #1976d2;")
        details_layout.addWidget(self.key_detail_name, 0, 1)
        
        # 密钥平台
        details_layout.addWidget(QLabel("平台:"), 1, 0)
        self.key_detail_platform = QLabel("--")
        details_layout.addWidget(self.key_detail_platform, 1, 1)
        
        # 密钥值（加密显示）
        details_layout.addWidget(QLabel("密钥:"), 2, 0)
        key_value_layout = QHBoxLayout()
        self.key_detail_value = QLabel("--")
        self.key_detail_value.setStyleSheet("font-family: monospace; background-color: #f5f5f5; padding: 5px; border-radius: 3px;")
        key_value_layout.addWidget(self.key_detail_value)
        
        self.toggle_key_detail_button = QPushButton("👁️")
        self.toggle_key_detail_button.setMaximumWidth(40)
        self.toggle_key_detail_button.clicked.connect(self.toggle_key_detail_visibility)
        key_value_layout.addWidget(self.toggle_key_detail_button)
        
        details_layout.addLayout(key_value_layout, 2, 1)
        
        # 创建时间
        details_layout.addWidget(QLabel("创建时间:"), 3, 0)
        self.key_detail_created = QLabel("--")
        details_layout.addWidget(self.key_detail_created, 3, 1)
        
        # 最后使用时间
        details_layout.addWidget(QLabel("最后使用:"), 4, 0)
        self.key_detail_last_used = QLabel("--")
        details_layout.addWidget(self.key_detail_last_used, 4, 1)
        
        right_layout.addWidget(self.key_details_widget)
        
        # 使用说明
        tips_layout = QVBoxLayout()
        tips_label = QLabel("""
<b>使用说明:</b><br>
• 点击"新建密钥"添加新的API密钥<br>
• 为每个密钥设置容易识别的名称<br>
• 在基础配置中可以快速切换密钥<br>
• 支持云雾AI、API易、apicore三个平台<br>
• 密钥会安全保存在本地配置文件中
        """)
        tips_label.setWordWrap(True)
        tips_label.setStyleSheet("color: #666; background-color: #f8f9fa; padding: 10px; border-radius: 6px; font-size: 12px;")
        tips_layout.addWidget(tips_label)
        
        right_layout.addLayout(tips_layout)
        right_layout.addStretch()
        
        # 添加到分割器
        main_splitter.addWidget(left_widget)
        main_splitter.addWidget(right_widget)
        main_splitter.setSizes([250, 550])
        
        layout.addWidget(main_splitter)
        
        # 初始化状态
        self.current_selected_key = ""
        self.key_detail_visible = False
        
        self.tab_widget.addTab(key_widget, "🔑 密钥库")
    

    
    def select_save_path(self):
        """选择保存路径"""
        path = QFileDialog.getExistingDirectory(self, "选择保存路径")
        if path:
            self.path_input.setText(path)
    
    def load_settings(self):
        """加载设置到界面"""
        # 基础配置
        self.thread_spin.setValue(self.thread_count)
        self.retry_spin.setValue(self.retry_count)
        self.path_input.setText(self.save_path)
        
        # 风格库
        self.refresh_style_combo()
        self.refresh_style_list()
        if self.current_style and self.current_style in self.style_library:
            self.style_combo.setCurrentText(self.current_style)
            # 确保custom_style_content与选择的风格同步
            if not self.custom_style_content or self.custom_style_content.strip() == "":
                self.custom_style_content = self.style_library[self.current_style]['content']
        
        # 参考图
        self.refresh_category_list()
        
        # 密钥库
        self.refresh_key_list()
        self.refresh_key_selector()
    
    def accept_settings(self):
        """确定：保存设置并关闭"""
        if self.parent():
            # 更新主窗口的配置
            self.parent().thread_count = self.thread_spin.value()
            self.parent().retry_count = self.retry_spin.value()
            self.parent().save_path = self.path_input.text()
            self.parent().style_library = self.style_library
            self.parent().category_links = self.category_links
            self.parent().current_style = self.current_style
            self.parent().custom_style_content = self.custom_style_content
            self.parent().key_library = self.key_library
            self.parent().current_key_name = self.current_key_name
            
            # 刷新主窗口界面
            self.parent().refresh_ui_after_settings()
            
            # 保存配置
            self.parent().save_config()
        
        # 关闭弹窗
        self.accept()
    
    # ========== 密钥库管理方法 ==========
    
    def refresh_key_list(self):
        """刷新密钥列表"""
        self.key_list.clear()
        for name, key_data in self.key_library.items():
            item = QListWidgetItem(name)
            platform = key_data.get('platform', '未知')
            last_used = key_data.get('last_used', '从未使用')
            item.setToolTip(f"平台: {platform}\n最后使用: {last_used}")
            
            # 如果是当前选中的密钥，高亮显示
            if name == self.current_key_name:
                item.setBackground(QColor("#e3f2fd"))
            
            self.key_list.addItem(item)
    
    def on_key_changed(self, current, previous):
        """密钥选择改变"""
        if current:
            key_name = current.text()
            self.current_selected_key = key_name
            self.load_key_details(key_name)
        else:
            self.current_selected_key = ""
            self.clear_key_details()
    
    def load_key_details(self, key_name):
        """加载密钥详情"""
        if key_name in self.key_library:
            key_data = self.key_library[key_name]
            self.key_detail_name.setText(key_data['name'])
            self.key_detail_platform.setText(key_data['platform'])
            
            # 默认隐藏密钥值
            self.key_detail_visible = False
            self.key_detail_value.setText("*" * 20)
            self.toggle_key_detail_button.setText("👁️")
            
            self.key_detail_created.setText(key_data.get('created_time', '未知'))
            self.key_detail_last_used.setText(key_data.get('last_used', '从未使用'))
    
    def clear_key_details(self):
        """清空密钥详情"""
        self.key_detail_name.setText("--")
        self.key_detail_platform.setText("--")
        self.key_detail_value.setText("--")
        self.key_detail_created.setText("--")
        self.key_detail_last_used.setText("--")
        self.toggle_key_detail_button.setText("👁️")
    
    def toggle_key_detail_visibility(self):
        """切换密钥详情显示/隐藏"""
        if not self.current_selected_key or self.current_selected_key not in self.key_library:
            return
        
        if self.key_detail_visible:
            self.key_detail_value.setText("*" * 20)
            self.toggle_key_detail_button.setText("👁️")
            self.key_detail_visible = False
        else:
            key_data = self.key_library[self.current_selected_key]
            self.key_detail_value.setText(key_data['api_key'])
            self.toggle_key_detail_button.setText("🙈")
            self.key_detail_visible = True
    
    def new_key(self):
        """新建密钥"""
        dialog = KeyEditDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            key_data = dialog.get_key_data()
            self.key_library[key_data['name']] = key_data
            self.refresh_key_list()
            self.refresh_key_selector()  # 同时刷新基础配置的密钥选择器
            # 选中新创建的密钥
            items = self.key_list.findItems(key_data['name'], Qt.MatchFlag.MatchExactly)
            if items:
                self.key_list.setCurrentItem(items[0])
    
    def edit_key(self):
        """编辑密钥"""
        if not self.current_selected_key:
            QMessageBox.warning(self, "提示", "请先选择要编辑的密钥")
            return
        
        key_data = self.key_library[self.current_selected_key]
        dialog = KeyEditDialog(self, key_data)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_key_data = dialog.get_key_data()
            
            # 如果名称改变了，需要删除旧的密钥
            if new_key_data['name'] != self.current_selected_key:
                del self.key_library[self.current_selected_key]
                # 如果当前使用的密钥名称改变了，需要更新current_key_name
                if self.current_key_name == self.current_selected_key:
                    self.current_key_name = new_key_data['name']
            
            self.key_library[new_key_data['name']] = new_key_data
            self.refresh_key_list()
            self.refresh_key_selector()  # 同时刷新基础配置的密钥选择器
            # 选中编辑后的密钥
            items = self.key_list.findItems(new_key_data['name'], Qt.MatchFlag.MatchExactly)
            if items:
                self.key_list.setCurrentItem(items[0])
    
    def delete_key(self):
        """删除密钥"""
        if not self.current_selected_key:
            QMessageBox.warning(self, "提示", "请先选择要删除的密钥")
            return
        
        reply = QMessageBox.question(
            self, 
            "确认删除", 
            f"确定要删除密钥 '{self.current_selected_key}' 吗？\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # 如果删除的是当前使用的密钥，清空当前密钥
            if self.current_key_name == self.current_selected_key:
                self.current_key_name = ""
            
            del self.key_library[self.current_selected_key]
            self.refresh_key_list()
            self.refresh_key_selector()  # 同时刷新基础配置的密钥选择器
            self.clear_key_details()
            self.current_selected_key = ""
    
    def refresh_key_selector(self):
        """刷新密钥选择下拉框"""
        self.key_selector_combo.blockSignals(True)
        self.key_selector_combo.clear()
        
        if not self.key_library:
            self.key_selector_combo.addItem("请先在密钥库中添加密钥...")
        else:
            self.key_selector_combo.addItem("-- 请选择密钥 --")
            # 添加所有密钥
            for key_name in self.key_library.keys():
                self.key_selector_combo.addItem(key_name)
        
        self.key_selector_combo.blockSignals(False)
        
        # 设置当前选中的密钥并更新显示
        if self.current_key_name and self.current_key_name in self.key_library:
            self.key_selector_combo.setCurrentText(self.current_key_name)
            self.update_key_display(self.current_key_name)
        else:
            self.clear_key_display()
    
    def on_key_selected(self, key_name):
        """密钥选择改变"""
        if key_name.startswith("请先在密钥库") or key_name.startswith("-- 请选择密钥"):
            self.current_key_name = ""
            self.clear_key_display()
        else:
            if key_name in self.key_library:
                key_data = self.key_library[key_name]
                self.current_key_name = key_name
                
                # 更新密钥显示
                self.update_key_display(key_name)
                
                # 更新最后使用时间
                key_data['last_used'] = time.strftime('%Y-%m-%d %H:%M:%S')
    
    def update_key_display(self, key_name):
        """更新密钥显示信息"""
        if key_name in self.key_library:
            key_data = self.key_library[key_name]
            self.current_platform_label.setText(key_data['platform'])
            self.current_last_used_label.setText(key_data.get('last_used', '从未使用'))
    
    def clear_key_display(self):
        """清空密钥显示信息"""
        self.current_platform_label.setText("--")
        self.current_last_used_label.setText("--")
    
    # ========== 参考图管理辅助方法 ==========
    
    def check_image_name_unique(self, name, exclude_category=None, exclude_name=None):
        """检查图片名称是否全局唯一"""
        for category, images in self.category_links.items():
            # 如果指定了排除的分类和名称（编辑时使用），则跳过
            if exclude_category and exclude_name and category == exclude_category:
                for img in images:
                    if img['name'] == exclude_name:
                        continue
                    if img['name'] == name:
                        return False, category
            else:
                for img in images:
                    if img['name'] == name:
                        return False, category
        return True, None
    
    def get_unique_image_name(self, base_name, exclude_category=None, exclude_name=None):
        """获取唯一的图片名称"""
        unique, _ = self.check_image_name_unique(base_name, exclude_category, exclude_name)
        if unique:
            return base_name
        
        # 如果名称重复，添加数字后缀
        counter = 1
        while True:
            new_name = f"{base_name}_{counter}"
            unique, _ = self.check_image_name_unique(new_name, exclude_category, exclude_name)
            if unique:
                return new_name
            counter += 1
    
    # ========== 风格库管理方法 ==========
    
    def refresh_style_combo(self):
        """刷新风格选择下拉框"""
        self.style_combo.blockSignals(True)
        self.style_combo.clear()
        self.style_combo.addItem("选择风格...")
        
        for style_name in self.style_library.keys():
            self.style_combo.addItem(style_name)
        
        self.style_combo.blockSignals(False)
        
        # 同步更新主界面的风格选择器（如果主窗口存在且有风格选择器）
        if self.parent() and hasattr(self.parent(), 'main_style_combo'):
            self.parent().refresh_main_style_combo()
    
    def refresh_style_list(self):
        """刷新风格列表"""
        self.style_list.clear()
        for name, style_data in self.style_library.items():
            item = QListWidgetItem(name)
            usage_count = style_data.get('usage_count', 0)
            item.setToolTip(f"使用次数: {usage_count}\n分类: {style_data.get('category', '未分类')}\n创建时间: {style_data.get('created_time', '未知')}")
            self.style_list.addItem(item)
    
    def on_style_changed(self, style_name):
        """风格选择改变时的处理"""
        if style_name == "选择风格..." or style_name == "":
            self.current_style = ""
            self.custom_style_content = ""  # 清空自定义风格内容
        else:
            if style_name in self.style_library:
                self.current_style = style_name
                # 重要：将选中的风格内容同步到custom_style_content
                self.custom_style_content = self.style_library[style_name]['content']
                # 在列表中选中对应项
                items = self.style_list.findItems(style_name, Qt.MatchFlag.MatchExactly)
                if items:
                    self.style_list.setCurrentItem(items[0])
    
    def on_style_list_changed(self, current, previous):
        """风格列表选择改变"""
        if current:
            style_name = current.text()
            if style_name in self.style_library:
                self.load_style_to_editor(style_name)
                self.current_style_name = style_name
                # 更新风格选择状态
                self.current_style = style_name
                self.custom_style_content = self.style_library[style_name]['content']
                # 同步到下拉框
                self.style_combo.blockSignals(True)
                self.style_combo.setCurrentText(style_name)
                self.style_combo.blockSignals(False)
        else:
            self.clear_style_editor()
            self.current_style_name = ""
            self.current_style = ""
            self.custom_style_content = ""
    
    def load_style_to_editor(self, style_name):
        """将风格加载到编辑器"""
        style_data = self.style_library[style_name]
        self.style_name_input.setText(style_name)
        self.style_content_edit.setPlainText(style_data['content'])
        self.update_style_char_count()
    
    def clear_style_editor(self):
        """清空风格编辑器"""
        self.style_name_input.clear()
        self.style_content_edit.clear()
        self.update_style_char_count()
    
    def update_style_char_count(self):
        """更新字符计数"""
        name_len = len(self.style_name_input.text())
        content_len = len(self.style_content_edit.toPlainText())
        self.style_char_count.setText(f"名称: {name_len} 字符 | 内容: {content_len} 字符")
    
    def on_style_content_changed(self):
        """风格内容改变时的处理"""
        # 实时更新custom_style_content，确保与编辑器内容同步
        self.custom_style_content = self.style_content_edit.toPlainText()
    
    def new_style(self):
        """新建风格"""
        new_name = self.generate_new_style_name()
        
        new_style = {
            'name': new_name,
            'content': '',
            'category': '自定义风格',
            'created_time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'usage_count': 0
        }
        
        self.style_library[new_name] = new_style
        self.refresh_style_list()
        self.refresh_style_combo()
        
        items = self.style_list.findItems(new_name, Qt.MatchFlag.MatchExactly)
        if items:
            self.style_list.setCurrentItem(items[0])
    
    def generate_new_style_name(self):
        """生成新的风格名称"""
        base_name = "新风格"
        counter = 1
        new_name = base_name
        
        while new_name in self.style_library:
            new_name = f"{base_name}{counter}"
            counter += 1
        
        return new_name
    
    def copy_style(self):
        """复制当前选中的风格"""
        if not self.current_style_name:
            QMessageBox.warning(self, "提示", "请先选择要复制的风格")
            return
        
        original_style = self.style_library[self.current_style_name]
        copy_name = f"{self.current_style_name}_副本"
        counter = 1
        
        while copy_name in self.style_library:
            copy_name = f"{self.current_style_name}_副本{counter}"
            counter += 1
        
        copied_style = {
            'name': copy_name,
            'content': original_style['content'],
            'category': original_style['category'],
            'created_time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'usage_count': 0
        }
        
        self.style_library[copy_name] = copied_style
        self.refresh_style_list()
        self.refresh_style_combo()
        
        items = self.style_list.findItems(copy_name, Qt.MatchFlag.MatchExactly)
        if items:
            self.style_list.setCurrentItem(items[0])
    
    def delete_style(self):
        """删除当前选中的风格"""
        if not self.current_style_name:
            QMessageBox.warning(self, "提示", "请先选择要删除的风格")
            return
        
        reply = QMessageBox.question(
            self, 
            "确认删除", 
            f"确定要删除风格 '{self.current_style_name}' 吗？\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            del self.style_library[self.current_style_name]
            self.refresh_style_list()
            self.refresh_style_combo()
            self.clear_style_editor()
            self.current_style_name = ""
    
    def save_current_style(self):
        """保存当前编辑的风格"""
        new_name = self.style_name_input.text().strip()
        new_content = self.style_content_edit.toPlainText().strip()
        
        if not new_name:
            QMessageBox.warning(self, "错误", "风格名称不能为空！")
            return
        
        if not new_content:
            QMessageBox.warning(self, "错误", "风格内容不能为空！")
            return
        
        if new_name != self.current_style_name and new_name in self.style_library:
            QMessageBox.warning(self, "错误", f"风格名称 '{new_name}' 已存在！")
            return
        
        if self.current_style_name and new_name != self.current_style_name:
            old_data = self.style_library[self.current_style_name]
            del self.style_library[self.current_style_name]
            
            self.style_library[new_name] = {
                'name': new_name,
                'content': new_content,
                'category': old_data.get('category', '自定义风格'),
                'created_time': old_data.get('created_time', time.strftime('%Y-%m-%d %H:%M:%S')),
                'usage_count': old_data.get('usage_count', 0)
            }
        else:
            if self.current_style_name in self.style_library:
                self.style_library[self.current_style_name]['content'] = new_content
                if new_name != self.current_style_name:
                    self.style_library[self.current_style_name]['name'] = new_name
            else:
                self.style_library[new_name] = {
                    'name': new_name,
                    'content': new_content,
                    'category': '自定义风格',
                    'created_time': time.strftime('%Y-%m-%d %H:%M:%S'),
                    'usage_count': 0
                }
        
        self.current_style_name = new_name
        self.refresh_style_list()
        self.refresh_style_combo()
        
        items = self.style_list.findItems(new_name, Qt.MatchFlag.MatchExactly)
        if items:
            self.style_list.setCurrentItem(items[0])
        
        QMessageBox.information(self, "成功", f"风格 '{new_name}' 已保存！")
    
    def import_styles(self):
        """从文件导入风格"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "导入风格文件", 
            "", 
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    imported_data = json.load(f)
                
                imported_count = 0
                for name, style_data in imported_data.items():
                    final_name = name
                    counter = 1
                    while final_name in self.style_library:
                        final_name = f"{name}_导入{counter}"
                        counter += 1
                    
                    self.style_library[final_name] = style_data
                    imported_count += 1
                
                self.refresh_style_list()
                self.refresh_style_combo()
                QMessageBox.information(self, "导入成功", f"成功导入 {imported_count} 个风格")
                
            except Exception as e:
                QMessageBox.critical(self, "导入失败", f"导入风格失败: {str(e)}")
    
    def export_styles(self):
        """导出风格到文件"""
        if not self.style_library:
            QMessageBox.warning(self, "提示", "没有可导出的风格")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出风格文件",
            f"nanobana_styles_{time.strftime('%Y%m%d_%H%M%S')}.json",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(self.style_library, f, indent=2, ensure_ascii=False)
                
                QMessageBox.information(self, "导出成功", f"已导出 {len(self.style_library)} 个风格到:\n{file_path}")
                
            except Exception as e:
                QMessageBox.critical(self, "导出失败", f"导出风格失败: {str(e)}")
    
    def reset_default_styles(self):
        """重置为默认风格"""
        reply = QMessageBox.question(
            self,
            "确认重置",
            "确定要重置为默认风格库吗？\n这将清除所有自定义风格！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.style_library = {}
            
            self.refresh_style_list()
            self.refresh_style_combo()
            self.clear_style_editor()
            self.current_style_name = ""
            
            QMessageBox.information(self, "重置完成", "已重置为默认风格库")
    
    # ========== 参考图管理方法 ==========
    
    def refresh_category_list(self):
        """刷新分类列表"""
        self.category_list.clear()
        for category in self.category_links.keys():
            item = QListWidgetItem(category)
            image_count = len(self.category_links[category])
            item.setToolTip(f"图片数量: {image_count}")
            self.category_list.addItem(item)
    
    def on_category_changed(self, current, previous):
        """分类选择改变"""
        if current:
            category_name = current.text()
            self.current_category = category_name
            self.load_images_to_table(category_name)
        else:
            self.clear_image_table()
            self.current_category = ""
    
    def load_images_to_table(self, category_name):
        """将图片加载到表格"""
        images = self.category_links.get(category_name, [])
        self.image_table.setRowCount(len(images))
        
        self.image_table.blockSignals(True)
        for row, image in enumerate(images):
            name_item = QTableWidgetItem(image.get('name', ''))
            self.image_table.setItem(row, 0, name_item)
            
            # 显示路径或URL
            if 'path' in image and image['path']:
                # 本地图片，显示路径
                path_item = QTableWidgetItem(image['path'])
                path_item.setToolTip(f"本地图片: {image['path']}")
            else:
                # 网络图片，显示URL
                path_item = QTableWidgetItem(image.get('url', ''))
                path_item.setToolTip(f"网络图片: {image.get('url', '')}")
            
            self.image_table.setItem(row, 1, path_item)
        self.image_table.blockSignals(False)
    
    def clear_image_table(self):
        """清空图片表格"""
        self.image_table.setRowCount(0)
    
    def new_category(self):
        """新建分类"""
        name, ok = QInputDialog.getText(self, "新建分类", "请输入分类名称:")
        if ok and name and name not in self.category_links:
            # 创建分类配置
            self.category_links[name] = []
            # 创建分类目录
            create_category_directory(name)
            self.refresh_category_list()
            items = self.category_list.findItems(name, Qt.MatchFlag.MatchExactly)
            if items:
                self.category_list.setCurrentItem(items[0])
            logging.info(f"创建新分类: {name}")
        elif ok and name in self.category_links:
            QMessageBox.warning(self, "错误", "分类名称已存在！")
    
    def rename_category(self):
        """重命名当前分类"""
        if not self.current_category:
            QMessageBox.warning(self, "提示", "请先选择要重命名的分类")
            return
            
        name, ok = QInputDialog.getText(self, "重命名分类", "请输入新名称:", text=self.current_category)
        if ok and name and name != self.current_category:
            if name in self.category_links:
                QMessageBox.warning(self, "错误", "分类名称已存在！")
                return
            
            # 更新配置
            old_category = self.current_category
            self.category_links[name] = self.category_links.pop(self.current_category)
            
            # 重命名目录
            rename_category_directory(old_category, name)
            
            # 更新图片路径（如果有本地图片的话）
            for image in self.category_links[name]:
                if 'path' in image and image['path'].startswith(f"images/{old_category}/"):
                    image['path'] = image['path'].replace(f"images/{old_category}/", f"images/{name}/")
            
            self.current_category = name
            self.refresh_category_list()
            
            items = self.category_list.findItems(name, Qt.MatchFlag.MatchExactly)
            if items:
                self.category_list.setCurrentItem(items[0])
            
            logging.info(f"重命名分类: {old_category} -> {name}")
    
    def delete_category(self):
        """删除当前选中的分类"""
        if not self.current_category:
            QMessageBox.warning(self, "提示", "请先选择要删除的分类")
            return
        
        reply = QMessageBox.question(
            self, 
            "确认删除", 
            f"确定要删除分类 '{self.current_category}' 吗？\n此操作会删除分类目录下的所有图片文件，不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # 删除目录及其内容
            delete_category_directory(self.current_category)
            # 删除配置
            del self.category_links[self.current_category]
            self.refresh_category_list()
            self.clear_image_table()
            logging.info(f"删除分类: {self.current_category}")
            self.current_category = ""
    
    def add_image(self):
        """添加图片"""
        if not self.current_category:
            QMessageBox.warning(self, "提示", "请先选择分类")
            return
        
        # 弹出文件选择对话框
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择图片文件",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;所有文件 (*)"
        )
        
        if file_path:
            # 获取图片名称（用户可以修改）
            default_name = Path(file_path).stem
            
            while True:
                name, ok = QInputDialog.getText(
                    self, 
                    "输入图片名称", 
                    "请输入图片名称（用于在提示词中引用）:\n注意：图片名称在全局范围内必须唯一",
                    text=default_name
                )
                
                if not ok:
                    return
                    
                if not name.strip():
                    QMessageBox.warning(self, "提示", "图片名称不能为空")
                    continue
                
                name = name.strip()
                
                # 检查名称是否全局唯一
                unique, existing_category = self.check_image_name_unique(name)
                if not unique:
                    reply = QMessageBox.question(
                        self, 
                        "名称重复", 
                        f"图片名称 '{name}' 已存在于分类 '{existing_category}' 中。\n\n"
                        f"是否使用建议的唯一名称 '{self.get_unique_image_name(name)}' ？",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                        QMessageBox.StandardButton.Yes
                    )
                    
                    if reply == QMessageBox.StandardButton.Yes:
                        name = self.get_unique_image_name(name)
                        break
                    elif reply == QMessageBox.StandardButton.No:
                        default_name = name  # 保持用户输入的名称作为下次的默认值
                        continue
                    else:  # Cancel
                        return
                else:
                    break
            
            try:
                # 复制图片到分类目录
                relative_path = copy_image_to_category(file_path, self.current_category, name)
                
                # 添加到配置中
                images = self.category_links[self.current_category]
                images.append({
                    'name': name,
                    'path': relative_path,
                    'url': ''  # 保留URL字段以兼容旧版本
                })
                
                self.load_images_to_table(self.current_category)
                QMessageBox.information(self, "成功", f"图片 '{name}' 已添加到分类 '{self.current_category}'")
                
            except Exception as e:
                QMessageBox.critical(self, "错误", f"添加图片失败: {str(e)}")
                logging.error(f"添加图片失败: {e}")
    
    def delete_image(self):
        """删除选中的图片"""
        if not self.current_category:
            QMessageBox.warning(self, "提示", "请先选择分类")
            return
        
        selected_rows = set(idx.row() for idx in self.image_table.selectedIndexes())
        if not selected_rows:
            QMessageBox.warning(self, "提示", "请先选择要删除的图片")
            return
        
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除选中的 {len(selected_rows)} 张图片吗？\n此操作会删除本地图片文件，不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            images = self.category_links[self.current_category]
            deleted_count = 0
            
            for row in sorted(selected_rows, reverse=True):
                if 0 <= row < len(images):
                    image = images[row]
                    
                    # 删除本地文件（如果存在path字段）
                    if 'path' in image and image['path']:
                        local_path = APP_PATH / image['path']
                        if local_path.exists():
                            try:
                                local_path.unlink()
                                logging.info(f"删除本地图片文件: {local_path}")
                            except Exception as e:
                                logging.error(f"删除本地图片文件失败: {e}")
                    
                    # 从配置中删除
                    images.pop(row)
                    deleted_count += 1
            
            self.load_images_to_table(self.current_category)
            if deleted_count > 0:
                QMessageBox.information(self, "删除完成", f"已删除 {deleted_count} 张图片")
    
    def on_image_changed(self, row, column):
        """图片信息改变时"""
        if not self.current_category:
            return
        
        images = self.category_links[self.current_category]
        if 0 <= row < len(images):
            name = self.image_table.item(row, 0).text() if self.image_table.item(row, 0) else ''
            path_or_url = self.image_table.item(row, 1).text() if self.image_table.item(row, 1) else ''
            
            # 如果修改的是名称列（column 0），需要检查唯一性
            if column == 0 and name.strip():
                old_name = images[row]['name']
                new_name = name.strip()
                
                # 如果名称确实改变了，检查全局唯一性
                if new_name != old_name:
                    unique, existing_category = self.check_image_name_unique(new_name, self.current_category, old_name)
                    if not unique:
                        QMessageBox.warning(
                            self, 
                            "名称重复", 
                            f"图片名称 '{new_name}' 已存在于分类 '{existing_category}' 中。\n"
                            f"图片名称在全局范围内必须唯一。"
                        )
                        # 恢复原名称
                        self.image_table.item(row, 0).setText(old_name)
                        return
            
            # 如果是路径格式（以images/开头），更新path字段；否则更新url字段
            if path_or_url.startswith('images/'):
                images[row] = {'name': name, 'path': path_or_url, 'url': images[row].get('url', '')}
            else:
                images[row] = {'name': name, 'url': path_or_url, 'path': images[row].get('path', '')}
    
    def on_image_table_double_clicked(self, row, column):
        """图片表格双击事件 - 预览图片"""
        if not self.current_category:
            return
        
        images = self.category_links[self.current_category]
        if 0 <= row < len(images):
            image = images[row]
            image_name = image.get('name', '')
            
            if 'path' in image and image['path']:
                # 本地图片预览
                local_path = APP_PATH / image['path']
                if local_path.exists():
                    self.show_image_preview(image_name, str(local_path), is_local=True)
                else:
                    QMessageBox.warning(self, "文件不存在", f"本地图片文件不存在:\n{local_path}")
            elif 'url' in image and image['url']:
                # 网络图片预览（显示URL信息）
                self.show_image_preview(image_name, image['url'], is_local=False)
            else:
                QMessageBox.information(self, "提示", "该图片没有有效的路径或链接")
    
    def show_image_preview(self, image_name, path_or_url, is_local=True):
        """显示图片预览对话框"""
        dialog = QDialog(self)
        dialog.setWindowTitle(f"图片预览 - {image_name}")
        dialog.resize(600, 500)
        
        layout = QVBoxLayout(dialog)
        
        # 图片显示区域
        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setStyleSheet("border: 1px solid #ddd; background-color: #f9f9f9;")
        image_label.setMinimumSize(500, 400)
        
        if is_local:
            # 本地图片
            try:
                pixmap = QPixmap(path_or_url)
                if not pixmap.isNull():
                    # 缩放图片以适应显示区域
                    scaled_pixmap = pixmap.scaled(
                        480, 380,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    image_label.setPixmap(scaled_pixmap)
                else:
                    image_label.setText("无法加载图片")
            except Exception as e:
                image_label.setText(f"加载图片失败:\n{str(e)}")
        else:
            # 网络图片显示链接信息
            image_label.setText(f"网络图片:\n{path_or_url}\n\n(双击此区域在浏览器中打开)")
            image_label.setWordWrap(True)
            image_label.mousePressEvent = lambda event: self.open_url_in_browser(path_or_url)
            image_label.setStyleSheet("border: 1px solid #ddd; background-color: #f0f8ff; padding: 20px; cursor: pointer;")
        
        layout.addWidget(image_label)
        
        # 信息标签
        info_label = QLabel(f"图片名称: {image_name}\n路径: {path_or_url}")
        info_label.setStyleSheet("color: #666; font-size: 12px; padding: 10px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # 关闭按钮
        close_button = QPushButton("关闭")
        close_button.clicked.connect(dialog.close)
        layout.addWidget(close_button)
        
        dialog.exec()
    
    def open_url_in_browser(self, url):
        """在浏览器中打开URL"""
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法打开链接: {str(e)}")

class PromptEditDialog(QDialog):
    """提示词编辑对话框"""
    
    def __init__(self, prompt_text, prompt_number, parent=None):
        super().__init__(parent)
        self.prompt_text = prompt_text
        self.prompt_number = prompt_number
        self.setWindowTitle(f"编辑提示词 - 编号: {prompt_number}")
        self.setModal(True)
        self.resize(700, 500)
        self.setMinimumSize(600, 400)
        
        # 设置窗口居中
        self.center_on_screen()
        
        self.setup_ui()
        
        # 设置样式
        self.setStyleSheet("""
            QDialog {
                background-color: #f5f5f5;
            }
            QTextEdit {
                border: 2px solid #ddd;
                border-radius: 8px;
                padding: 12px;
                font-size: 14px;
                background-color: white;
                line-height: 1.5;
            }
            QTextEdit:focus {
                border-color: #1976d2;
            }
            QPushButton {
                padding: 10px 20px;
                font-size: 14px;
                font-weight: bold;
                border-radius: 6px;
            }
            QPushButton#confirm {
                background-color: #4caf50;
                color: white;
                border: none;
            }
            QPushButton#confirm:hover {
                background-color: #45a049;
            }
            QPushButton#cancel {
                background-color: #f44336;
                color: white;
                border: none;
            }
            QPushButton#cancel:hover {
                background-color: #da190b;
            }
        """)
    
    def center_on_screen(self):
        """将对话框居中显示"""
        if self.parent():
            parent_geometry = self.parent().geometry()
            x = parent_geometry.x() + (parent_geometry.width() - self.width()) // 2
            y = parent_geometry.y() + (parent_geometry.height() - self.height()) // 2
            self.move(x, y)
    
    def setup_ui(self):
        """设置UI界面"""
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 标题和说明
        title_label = QLabel(f"📝 编辑提示词 (编号: {self.prompt_number})")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #333; margin-bottom: 10px;")
        layout.addWidget(title_label)
        
        # 提示信息
        hint_label = QLabel("💡 在下方文本框中编辑您的提示词，支持多行文本和换行。")
        hint_label.setStyleSheet("color: #666; font-size: 12px; margin-bottom: 10px;")
        layout.addWidget(hint_label)
        
        # 文本编辑区域
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlainText(self.prompt_text)
        self.text_edit.setPlaceholderText("请输入您的提示词内容...")
        
        # 设置字体
        font = QFont()
        font.setFamily("Microsoft YaHei")
        font.setPointSize(11)
        self.text_edit.setFont(font)
        
        layout.addWidget(self.text_edit)
        
        # 字符计数标签
        self.char_count_label = QLabel()
        self.char_count_label.setStyleSheet("color: #666; font-size: 12px;")
        self.update_char_count()
        layout.addWidget(self.char_count_label)
        
        # 连接文本变化事件
        self.text_edit.textChanged.connect(self.update_char_count)
        
        # 按钮区域
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        # 取消按钮
        cancel_button = QPushButton("❌ 取消")
        cancel_button.setObjectName("cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)
        
        # 确认按钮
        confirm_button = QPushButton("✅ 确认保存")
        confirm_button.setObjectName("confirm")
        confirm_button.clicked.connect(self.accept)
        confirm_button.setDefault(True)  # 设置为默认按钮
        button_layout.addWidget(confirm_button)
        
        layout.addLayout(button_layout)
        
        # 设置焦点到文本编辑框
        self.text_edit.setFocus()
        
        # 选中所有文本，方便编辑
        self.text_edit.selectAll()
        
        # 添加快捷键支持
        from PyQt6.QtGui import QShortcut, QKeySequence
        
        # Ctrl+S 保存
        save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        save_shortcut.activated.connect(self.accept)
        
        # Esc 取消
        cancel_shortcut = QShortcut(QKeySequence("Esc"), self)
        cancel_shortcut.activated.connect(self.reject)
    
    def update_char_count(self):
        """更新字符计数"""
        text = self.text_edit.toPlainText()
        char_count = len(text)
        line_count = len(text.split('\n'))
        self.char_count_label.setText(f"📊 字符数: {char_count} | 行数: {line_count}")
    
    def get_text(self):
        """获取编辑后的文本"""
        return self.text_edit.toPlainText().strip()

class ImageViewDialog(QDialog):
    """图片查看对话框"""
    
    def __init__(self, image_number, prompt_text, save_path, parent=None, actual_filename=None):
        super().__init__(parent)
        self.image_number = image_number
        self.prompt_text = prompt_text
        self.save_path = save_path
        self.actual_filename = actual_filename
        self.setWindowTitle(f"图片预览 - {prompt_text[:30]}...")
        self.setModal(True)
        self.resize(800, 600)
        
        layout = QVBoxLayout(self)
        
        # 图片显示区域
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("border: 1px solid #ddd; background-color: #f9f9f9;")
        self.image_label.setText("正在加载图片...")
        
        layout.addWidget(self.image_label)
        
        # 底部信息和按钮
        info_layout = QHBoxLayout()
        
        info_label = QLabel(f"提示词: {prompt_text}")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #666; font-size: 12px;")
        info_layout.addWidget(info_label)
        
        info_layout.addStretch()
        
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.close)
        info_layout.addWidget(close_button)
        
        layout.addLayout(info_layout)
        
        # 加载图片
        self.load_image()
    
    def load_image(self):
        """从本地文件加载并显示图片"""
        try:
            # 检查保存路径
            if not self.save_path:
                self.image_label.setText("保存路径未设置")
                return
            
            # 直接使用基础文件名
            filename = f"{self.image_number}.png"
            file_path = os.path.join(self.save_path, filename)
            
            # 检查文件是否存在
            if not os.path.exists(file_path):
                self.image_label.setText(f"本地图片文件不存在:\n{filename}")
                return
            
            # 从本地文件加载图片
            pixmap = QPixmap(file_path)
            
            if not pixmap.isNull():
                # 缩放图片以适应窗口，保持比例
                scaled_pixmap = pixmap.scaled(
                    self.image_label.size() - QSize(20, 20),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.image_label.setPixmap(scaled_pixmap)
            else:
                self.image_label.setText("图片文件格式错误")
                
        except Exception as e:
            self.image_label.setText(f"本地图片加载失败:\n{str(e)}")
    
    def find_actual_image_file(self, image_number, save_path):
        """查找实际的图片文件名"""
        import os
        
        # 只查找基础文件名
        base_filename = f"{image_number}.png"
        base_file_path = os.path.join(save_path, base_filename)
        
        # 检查基础文件名是否存在
        if os.path.exists(base_file_path):
            return base_filename
        
        return None

class PromptTableDelegate(QStyledItemDelegate):
    """自定义表格委托，处理编辑和显示"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
    
    def createEditor(self, parent, option, index):
        """创建编辑器"""
        if index.column() == 0:  # 编号列，允许直接编辑
            editor = QLineEdit(parent)
            editor.setStyleSheet("""
                QLineEdit {
                    border: 2px solid #1976d2;
                    border-radius: 4px;
                    padding: 4px;
                    background-color: white;
                }
            """)
            return editor
        elif index.column() == 1:  # 提示词列，禁用编辑（使用双击对话框）
            return None  # 返回None禁用编辑
        return super().createEditor(parent, option, index)
    
    def setEditorData(self, editor, index):
        """设置编辑器数据"""
        value = index.model().data(index, Qt.ItemDataRole.EditRole)
        if isinstance(editor, QLineEdit):
            editor.setText(str(value))
            editor.selectAll()
        else:
            super().setEditorData(editor, index)
    
    def setModelData(self, editor, model, index):
        """将编辑器数据设置回模型"""
        if isinstance(editor, QLineEdit):
            # 移除首尾空白字符
            text = editor.text().strip()
            model.setData(index, text, Qt.ItemDataRole.EditRole)
        else:
            super().setModelData(editor, model, index)
    
    def paint(self, painter, option, index):
        """自定义绘制，支持换行显示"""
        if index.column() == 1:  # 提示词列
            text = index.data(Qt.ItemDataRole.DisplayRole)
            if text:
                # 设置绘制区域
                rect = option.rect
                rect.adjust(8, 5, -8, -5)  # 添加一些边距
                
                # 设置字体和颜色
                painter.setFont(option.font)
                painter.setPen(option.palette.color(QPalette.ColorRole.Text))
                
                # 如果选中，设置选中样式
                if option.state & QStyle.StateFlag.State_Selected:
                    painter.fillRect(option.rect, option.palette.color(QPalette.ColorRole.Highlight))
                    painter.setPen(option.palette.color(QPalette.ColorRole.HighlightedText))
                
                # 绘制文本，支持换行和换行符
                painter.drawText(rect, Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, text)
                return
        
        # 其他列使用默认绘制
        super().paint(painter, option, index)
    
    def sizeHint(self, option, index):
        """计算单元格大小提示"""
        if index.column() == 1:  # 提示词列
            text = index.data(Qt.ItemDataRole.DisplayRole)
            if text:
                # 计算文本需要的高度
                font_metrics = option.fontMetrics
                # 获取列宽
                column_width = 300  # 默认宽度，实际会由表格调整
                if hasattr(option, 'rect'):
                    column_width = option.rect.width() - 10  # 减去边距
                
                # 计算换行后的高度
                text_rect = font_metrics.boundingRect(0, 0, column_width, 0, Qt.TextFlag.TextWordWrap, text)
                height = max(200, text_rect.height() + 20)  # 最小200像素，与图片行高保持一致
                return QSize(column_width, height)
        
        return super().sizeHint(option, index)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._init_done = False
        self.setWindowTitle("Nano banana 批量出图 V4.0 by 大臣")
        self.resize(1200, 800)
        self.setMinimumSize(1000, 600)
        
        # 配置变量
        self.api_key = ""
        self.api_platform = "云雾"
        self.thread_count = 5
        self.retry_count = 3
        self.save_path = ""
        self.style_library = {}
        self.category_links = {}
        self.current_style = ""
        self.custom_style_content = ""
        
        # 密钥库相关变量
        self.key_library = {}  # 存储所有密钥 {name: {name, api_key, platform, created_time, last_used}}
        self.current_key_name = ""  # 当前选中的密钥名称
        
        # 添加计数器变量
        self.total_images = 0
        self.completed_images = 0
        
        # 提示词数据存储
        self.prompt_table_data = []  # [{number, prompt, status, image_url, error_msg}]
        
        # 设置现代化样式
        self.setup_modern_style()
        
        # 创建主窗口
        self.setup_ui()
        
        # 初始化异步任务管理
        self.async_tasks = set()  # 存储当前运行的异步任务
        self.max_concurrent_tasks = self.thread_count  # 最大并发任务数
        self.semaphore = None  # 并发控制信号量，将在需要时创建
        
        # 存储提示词和编号的对应关系
        self.prompt_numbers = {}
        
        # 检查并自动生成默认配置文件
        self.check_default_config()
        
        # 加载配置
        self.load_config()
        
        # 确保图片目录存在
        ensure_images_directory()
        
        # 为现有分类创建目录（兼容旧版本）
        for category_name in self.category_links.keys():
            create_category_directory(category_name)
        
        # 存储生成的图片信息
        self.generated_images = {}
        
        self._init_done = True
        
        # 确保主界面风格选择器显示正确的当前风格
        if hasattr(self, 'main_style_combo'):
            self.refresh_main_style_combo()
        
        # 创建状态更新定时器，每秒更新一次线程池状态
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_thread_status)
        self.status_timer.start(1000)  # 每1000毫秒(1秒)更新一次
        
    def setup_modern_style(self):
        """设置现代化样式"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            
            QGroupBox {
                font-weight: bold;
                border: 2px solid #ddd;
                border-radius: 8px;
                margin-top: 1ex;
                padding-top: 10px;
                background-color: white;
            }
            
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #333;
            }
            
            QPushButton {
                background-color: #1976d2;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: 500;
            }
            
            QPushButton:hover {
                background-color: #1565c0;
            }
            
            QPushButton:pressed {
                background-color: #0d47a1;
            }
            
            QPushButton:disabled {
                background-color: #ccc;
            }
            
            QLineEdit, QComboBox, QSpinBox {
                padding: 8px;
                border: 1px solid #ddd;
                border-radius: 4px;
                background-color: white;
            }
            
            QLineEdit:focus, QComboBox:focus {
                border-color: #1976d2;
            }
            
            QListWidget {
                border: 1px solid #ddd;
                border-radius: 4px;
                background-color: white;
            }
            
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #eee;
            }
            
            QListWidget::item:selected {
                background-color: #e3f2fd;
                color: #1976d2;
            }
            
            QTableWidget {
                border: 1px solid #ddd;
                border-radius: 4px;
                background-color: white;
                gridline-color: #eee;
                selection-background-color: #e9ecef;
                selection-color: black;
            }
            
            QTableWidget::item {
                padding: 8px;
                border: none;
            }
            
            QTableWidget::item:selected {
                background-color: #e9ecef;
                color: black;
                border: none;
            }
            
            QTableWidget::item:focus {
                background-color: #e9ecef;
                border: none;
                outline: none;
            }
            
            QTextEdit, QPlainTextEdit {
                border: 1px solid #ddd;
                border-radius: 4px;
                background-color: white;
                padding: 8px;
            }
        """)
    
    def setup_ui(self):
        """设置优化后的UI布局"""
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        
        main_layout = QVBoxLayout(main_widget)
        main_layout.setSpacing(16)
        main_layout.setContentsMargins(16, 16, 16, 16)
        
        # 顶部工具栏
        self.create_toolbar(main_layout)
        
        # 主要内容区域
        self.create_main_content(main_layout)
        
        # 生成控制区域
        self.create_generation_card(main_layout)
    
    def create_toolbar(self, parent_layout):
        """创建顶部工具栏"""
        toolbar_layout = QHBoxLayout()
        
        # 左侧标题
        title_label = QLabel("🚀 Nano banana 批量出图工具")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #333; padding: 8px;")
        toolbar_layout.addWidget(title_label)
        
        toolbar_layout.addStretch()
        
        # 右侧工具按钮
        self.settings_button = QPushButton("⚙️ 设置中心")
        self.settings_button.setStyleSheet("""
            QPushButton {
                background-color: #424242;
                font-size: 14px;
                padding: 10px 20px;
            }
            QPushButton:hover {
                background-color: #616161;
            }
        """)
        self.settings_button.clicked.connect(self.open_settings)
        toolbar_layout.addWidget(self.settings_button)
        
        # 快捷状态显示
        self.quick_status_label = QLabel("API平台: 云雾 | 线程: 5 | 保存路径: 未设置")
        self.quick_status_label.setStyleSheet("color: #666; font-size: 12px; padding: 8px;")
        toolbar_layout.addWidget(self.quick_status_label)
        
        parent_layout.addLayout(toolbar_layout)
    
    def create_main_content(self, parent_layout):
        """创建主要内容区域"""
        main_card = QGroupBox("📝 提示词管理与生成")
        parent_layout.addWidget(main_card)
        
        layout = QVBoxLayout(main_card)
        
        # 顶部操作按钮
        button_layout = QHBoxLayout()
        
        self.import_csv_button = QPushButton("📁 导入CSV文件")
        self.import_csv_button.clicked.connect(self.import_csv)
        button_layout.addWidget(self.import_csv_button)
        
        self.add_prompt_button = QPushButton("➕ 添加提示词")
        self.add_prompt_button.clicked.connect(self.add_prompt)
        button_layout.addWidget(self.add_prompt_button)
        
        self.delete_prompt_button = QPushButton("🗑️ 删除选中")
        self.delete_prompt_button.clicked.connect(self.delete_selected_prompts)
        button_layout.addWidget(self.delete_prompt_button)
        
        self.clear_prompts_button = QPushButton("🗑️ 清空全部")
        self.clear_prompts_button.clicked.connect(self.clear_prompts)
        button_layout.addWidget(self.clear_prompts_button)
        
        # 导出提示词按钮
        self.export_prompts_button = QPushButton("📤 导出CSV")
        self.export_prompts_button.clicked.connect(self.export_prompts_to_csv)
        button_layout.addWidget(self.export_prompts_button)
        
        button_layout.addStretch()
        
        # 风格选择
        style_layout = QHBoxLayout()
        style_label = QLabel("🎨 风格:")
        style_label.setStyleSheet("color: #666; font-weight: bold;")
        style_layout.addWidget(style_label)
        
        self.main_style_combo = QComboBox()
        self.main_style_combo.setMinimumWidth(200)
        self.main_style_combo.setStyleSheet("""
            QComboBox {
                padding: 5px;
                border: 1px solid #ccc;
                border-radius: 4px;
                background-color: white;
            }
            QComboBox:hover {
                border-color: #2196f3;
            }
            QComboBox::drop-down {
                border: none;
                padding-right: 10px;
            }
        """)
        self.main_style_combo.currentTextChanged.connect(self.on_main_style_changed)
        style_layout.addWidget(self.main_style_combo)
        
        # 将风格选择添加到button_layout
        style_widget = QWidget()
        style_widget.setLayout(style_layout)
        button_layout.addWidget(style_widget)
        
        # 使用提示
        usage_hint = QLabel("💡 双击提示词可编辑")
        usage_hint.setStyleSheet("color: #666; font-size: 12px; font-style: italic;")
        button_layout.addWidget(usage_hint)
        
        # 统计信息
        self.prompt_stats_label = QLabel("总计: 0 个提示词")
        self.prompt_stats_label.setStyleSheet("color: #666; font-size: 14px;")
        button_layout.addWidget(self.prompt_stats_label)
        
        layout.addLayout(button_layout)
        
        # 提示词表格
        self.prompt_table = QTableWidget()
        self.prompt_table.setColumnCount(4)
        self.prompt_table.setHorizontalHeaderLabels(["编号", "提示词", "状态", "生成图片"])
        
        # 设置表格属性
        self.prompt_table.setAlternatingRowColors(False)  # 禁用斑马纹，全部白色背景
        self.prompt_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # 允许双击和F2键编辑
        self.prompt_table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        
        # 设置表格图标尺寸（重要：这决定了缩略图在表格中的显示大小）
        self.prompt_table.setIconSize(QSize(180, 180))
        
        # 设置列宽
        header = self.prompt_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)  # 编号列固定宽度
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # 提示词列自适应
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)  # 状态列固定宽度
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)  # 图片列固定宽度
        
        self.prompt_table.setColumnWidth(0, 80)   # 编号列
        self.prompt_table.setColumnWidth(2, 120)  # 状态列
        self.prompt_table.setColumnWidth(3, 220)  # 图片列（增加宽度以容纳180px缩略图）
        
        # 设置行高自适应内容
        self.prompt_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.prompt_table.verticalHeader().setMinimumSectionSize(200)  # 设置足够的行高以完整显示180px缩略图
        
        # 隐藏行号，避免与编号列混淆
        self.prompt_table.verticalHeader().setVisible(False)
        
        # 设置文本换行
        self.prompt_table.setWordWrap(True)
        
        # 设置自定义委托
        self.table_delegate = PromptTableDelegate()
        self.prompt_table.setItemDelegate(self.table_delegate)
        
        # 连接信号
        self.prompt_table.cellChanged.connect(self.on_table_cell_changed)
        self.prompt_table.cellDoubleClicked.connect(self.on_table_cell_double_clicked)
        
        layout.addWidget(self.prompt_table)
    
    def create_generation_card(self, parent_layout):
        """创建生成控制卡片"""
        generation_card = QGroupBox("🚀 生成控制")
        parent_layout.addWidget(generation_card)
        
        layout = QVBoxLayout(generation_card)
        
        # 生成按钮和进度信息
        control_layout = QHBoxLayout()
        
        # 智能生成按钮
        self.generate_button = QPushButton("🚀 智能生成(仅新增)")
        self.generate_button.setMinimumHeight(50)
        self.generate_button.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.generate_button.clicked.connect(self.start_generation)
        control_layout.addWidget(self.generate_button)
        
        # 重新生成选中按钮
        self.regenerate_selected_button = QPushButton("🔄 重新生成选中")
        self.regenerate_selected_button.setMinimumHeight(50)
        self.regenerate_selected_button.setStyleSheet("""
            QPushButton {
                background-color: #2196f3;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976d2;
            }
        """)
        self.regenerate_selected_button.clicked.connect(self.start_regenerate_selected)
        control_layout.addWidget(self.regenerate_selected_button)
        
        # 重新生成全部按钮
        self.regenerate_all_button = QPushButton("🔄 重新生成全部")
        self.regenerate_all_button.setMinimumHeight(50)
        self.regenerate_all_button.setStyleSheet("""
            QPushButton {
                background-color: #ff9800;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #f57c00;
            }
        """)
        self.regenerate_all_button.clicked.connect(self.start_regenerate_all)
        control_layout.addWidget(self.regenerate_all_button)
        
        # 进度信息
        progress_layout = QVBoxLayout()
        
        self.overall_progress_label = QLabel("等待开始...")
        self.overall_progress_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #333;")
        progress_layout.addWidget(self.overall_progress_label)
        
        self.overall_progress_bar = QProgressBar()
        self.overall_progress_bar.setVisible(False)
        progress_layout.addWidget(self.overall_progress_bar)
        
        control_layout.addLayout(progress_layout)
        
        layout.addLayout(control_layout)
    
    def open_settings(self):
        """打开设置中心"""
        dialog = SettingsDialog(self)
        dialog.exec()
    
    def refresh_ui_after_settings(self):
        """设置应用后刷新界面"""
        # 更新快捷状态显示
        save_status = "已设置" if self.save_path else "未设置"
        active_tasks = len(self.async_tasks) if hasattr(self, 'async_tasks') else 0
        max_tasks = self.max_concurrent_tasks if hasattr(self, 'max_concurrent_tasks') else self.thread_count
        self.quick_status_label.setText(f"API平台: {self.api_platform} | 并发任务: {active_tasks}/{max_tasks} | 保存路径: {save_status}")
        
        # 更新异步任务的最大并发数
        if hasattr(self, 'max_concurrent_tasks'):
            self.max_concurrent_tasks = self.thread_count
        
        # 刷新主界面的风格选择下拉框
        if hasattr(self, 'main_style_combo'):
            self.refresh_main_style_combo()
            
        # 如果当前密钥存在，自动应用密钥
        if self.current_key_name and self.current_key_name in self.key_library:
            key_data = self.key_library[self.current_key_name]
            self.api_key = key_data['api_key']
            self.api_platform = key_data['platform']
            # 更新最后使用时间
            key_data['last_used'] = time.strftime('%Y-%m-%d %H:%M:%S')
    
    def update_thread_status(self):
        """更新异步任务状态显示"""
        if hasattr(self, 'async_tasks') and hasattr(self, 'quick_status_label'):
            save_status = "已设置" if self.save_path else "未设置"
            active_tasks = len(self.async_tasks)
            max_tasks = self.max_concurrent_tasks
            self.quick_status_label.setText(f"API平台: {self.api_platform} | 并发任务: {active_tasks}/{max_tasks} | 保存路径: {save_status}")
    
    def run_async_worker(self, prompt, image_data_list, number, idx, original_prompt):
        """运行异步Worker"""
        try:
            # 在事件循环中运行异步任务
            future = asyncio.run_coroutine_threadsafe(
                self._execute_async_worker(prompt, image_data_list, number, idx, original_prompt),
                self.get_or_create_event_loop()
            )
            logging.info(f"创建异步任务: {prompt[:50]}...")
        except Exception as e:
            logging.error(f"创建异步任务失败: {e}")
            # 回退到错误处理
            self.handle_error(prompt, f"任务创建失败: {str(e)}", idx, original_prompt)
    
    def get_or_create_event_loop(self):
        """获取或创建事件循环"""
        if not hasattr(self, '_event_loop') or self._event_loop.is_closed():
            self._event_loop = asyncio.new_event_loop()
            # 在新线程中运行事件循环
            import threading
            def run_loop():
                asyncio.set_event_loop(self._event_loop)
                self._event_loop.run_forever()
            self._loop_thread = threading.Thread(target=run_loop, daemon=True)
            self._loop_thread.start()
        return self._event_loop
    
    async def _execute_async_worker(self, prompt, image_data_list, number, idx, original_prompt):
        """执行异步Worker"""
        # 创建信号对象
        signals = WorkerSignals()
        signals.finished.connect(lambda p, url, num: self.handle_success(p, url, num, idx, original_prompt))
        signals.error.connect(lambda p, err: self.handle_error(p, err, idx, original_prompt))
        signals.progress.connect(lambda p, status: self.handle_progress(p, status, original_prompt))
        
        # 创建异步Worker
        worker = AsyncWorker(prompt, self.api_key, image_data_list, self.api_platform, self.retry_count, number=number, signals=signals)
        
        # 控制并发数量
        if not self.semaphore:
            self.semaphore = asyncio.Semaphore(self.max_concurrent_tasks)
        
        # 创建任务
        task = asyncio.create_task(self._run_with_semaphore(worker))
        self.async_tasks.add(task)
        
        # 任务完成后清理
        task.add_done_callback(self.async_tasks.discard)
        
        return await task
    
    async def _run_with_semaphore(self, worker):
        """在信号量控制下运行Worker"""
        async with self.semaphore:
            await worker.run()
    
    def import_csv(self):
        """导入CSV文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择CSV文件",
            "",
            "CSV Files (*.csv)"
        )
        
        if file_path:
            try:
                # 尝试不同的编码方式读取CSV文件
                encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030']
                df = None
                
                for encoding in encodings:
                    try:
                        df = pd.read_csv(file_path, encoding=encoding)
                        break
                    except UnicodeDecodeError:
                        continue
                
                if df is None:
                    QMessageBox.critical(self, "错误", "无法读取CSV文件，请确保文件编码为UTF-8、GBK、GB2312或GB18030")
                    return
                
                # 检查是否存在"分镜提示词"列
                if "分镜提示词" not in df.columns:
                    QMessageBox.critical(self, "错误", "CSV文件中没有找到'分镜提示词'列")
                    return
                
                # 检查是否存在"分镜编号"列
                has_number_column = "分镜编号" in df.columns
                
                # 清空现有数据
                self.prompt_table_data.clear()
                self.prompt_numbers.clear()
                
                # 添加提示词到数据
                for index, row in df.iterrows():
                    prompt = row["分镜提示词"]
                    if pd.notna(prompt):
                        prompt_str = str(prompt)
                        
                        # 确定编号
                        if has_number_column:
                            number = row["分镜编号"]
                            if pd.notna(number):
                                display_number = str(number)
                            else:
                                display_number = str(index + 1)
                        else:
                            display_number = str(index + 1)
                        
                        # 添加到数据列表
                        self.prompt_table_data.append({
                            'number': display_number,
                            'prompt': prompt_str,
                            'status': '等待中',
                            'image_url': '',
                            'error_msg': ''
                        })
                        
                        self.prompt_numbers[prompt_str] = display_number
                
                # 刷新表格显示
                self.refresh_prompt_table()
                self.update_prompt_stats()
                QMessageBox.information(self, "成功", f"成功导入 {len(self.prompt_table_data)} 个提示词")
                
            except Exception as e:
                QMessageBox.critical(self, "错误", f"导入CSV文件失败: {str(e)}")
    
    def clear_prompts(self):
        """清空导入的提示词列表"""
        if not self.prompt_table_data:
            QMessageBox.warning(self, "提示", "当前没有提示词可以清空")
            return
        
        reply = QMessageBox.question(
            self,
            "确认清空",
            f"确定要清空所有 {len(self.prompt_table_data)} 个提示词吗？\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.prompt_table_data.clear()
            self.prompt_numbers.clear()
            self.refresh_prompt_table()
            self.update_prompt_stats()
            QMessageBox.information(self, "完成", "已清空所有提示词")
    
    def export_prompts_to_csv(self):
        """导出提示词到CSV文件"""
        if not self.prompt_table_data:
            QMessageBox.warning(self, "提示", "没有可导出的提示词数据")
            return
        
        # 选择保存路径
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出提示词",
            f"nanobana_prompts_{time.strftime('%Y%m%d_%H%M%S')}.csv",
            "CSV Files (*.csv);;All Files (*)"
        )
        
        if file_path:
            try:
                import pandas as pd
                
                # 准备导出数据
                export_data = []
                for data in self.prompt_table_data:
                    export_data.append({
                        '编号': data['number'],
                        '提示词': data['prompt'],
                        '状态': data['status'],
                        '错误信息': data.get('error_msg', ''),
                        '图片URL': data.get('image_url', '')
                    })
                
                # 创建DataFrame并导出
                df = pd.DataFrame(export_data)
                df.to_csv(file_path, index=False, encoding='utf-8-sig')
                
                QMessageBox.information(self, "导出成功", 
                    f"已成功导出 {len(export_data)} 个提示词到:\n{file_path}")
                
            except ImportError:
                QMessageBox.critical(self, "导出失败", "缺少pandas模块，无法导出CSV文件")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", f"导出过程中出现错误: {str(e)}")
    
    def refresh_main_style_combo(self):
        """刷新主界面的风格选择下拉框"""
        # 阻止信号触发，避免循环调用
        self.main_style_combo.blockSignals(True)
        
        current_text = self.main_style_combo.currentText()
        
        self.main_style_combo.clear()
        self.main_style_combo.addItem("选择风格...")
        
        for style_name in self.style_library.keys():
            self.main_style_combo.addItem(style_name)
        
        # 优先使用当前配置的风格，然后是之前的选择
        target_style = None
        if self.current_style and self.current_style in self.style_library:
            target_style = self.current_style
        elif current_text and current_text != "选择风格..." and current_text in self.style_library:
            target_style = current_text
        
        if target_style:
            self.main_style_combo.setCurrentText(target_style)
        else:
            self.main_style_combo.setCurrentIndex(0)  # 选择"选择风格..."
        
        # 恢复信号
        self.main_style_combo.blockSignals(False)
    
    def on_main_style_changed(self, style_name):
        """主界面风格选择变化处理"""
        if style_name == "选择风格..." or style_name == "":
            self.current_style = ""
            self.custom_style_content = ""
        else:
            if style_name in self.style_library:
                self.current_style = style_name
                self.custom_style_content = self.style_library[style_name]['content']
                
                # 更新使用次数
                self.style_library[style_name]['usage_count'] = self.style_library[style_name].get('usage_count', 0) + 1
        
        # 保存配置
        self.save_config()
    
    def update_prompt_stats(self):
        """更新提示词统计"""
        count = len(self.prompt_table_data)
        self.prompt_stats_label.setText(f"总计: {count} 个提示词")
    

    def refresh_prompt_table(self):
        """刷新提示词表格显示"""
        self.prompt_table.setRowCount(len(self.prompt_table_data))
        
        for row, data in enumerate(self.prompt_table_data):
            # 编号列
            number_item = QTableWidgetItem(data['number'])
            self.prompt_table.setItem(row, 0, number_item)
            
            # 提示词列
            prompt_item = QTableWidgetItem(data['prompt'])
            prompt_item.setToolTip("双击此处编辑提示词")  # 提示用户双击编辑
            # 设置为不可编辑，只能通过双击对话框编辑
            prompt_item.setFlags(prompt_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            # 设置文本对齐方式，支持换行
            prompt_item.setTextAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            self.prompt_table.setItem(row, 1, prompt_item)
            
            # 调整行高以适应内容
            self.prompt_table.resizeRowToContents(row)
            
            # 状态列
            status_item = QTableWidgetItem(data['status'])
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)  # 不可编辑
            self.update_status_style(status_item, data['status'])
            self.prompt_table.setItem(row, 2, status_item)
            
            # 图片列
            image_item = QTableWidgetItem()
            image_item.setFlags(image_item.flags() & ~Qt.ItemFlag.ItemIsEditable)  # 不可编辑
            # 设置图片居中对齐
            image_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.prompt_table.setItem(row, 3, image_item)
            # 在设置表格项后再更新图片显示，避免覆盖
            self.update_image_display(row, data)
    
    def update_status_style(self, item, status):
        """更新状态列样式"""
        if status == "等待中":
            item.setBackground(QColor("#f0f0f0"))
            item.setForeground(QColor("#666"))
        elif status == "生成中":
            item.setBackground(QColor("#e3f2fd"))
            item.setForeground(QColor("#1976d2"))
        elif status == "成功":
            item.setBackground(QColor("#e8f5e8"))
            item.setForeground(QColor("#388e3c"))
        elif status == "失败":
            item.setBackground(QColor("#ffebee"))
            item.setForeground(QColor("#d32f2f"))
    
    def update_image_display(self, row, data):
        """更新图片显示"""
        item = self.prompt_table.item(row, 3)
        if not item:
            return
            
        if data['status'] == '成功':
            # 加载缩略图
            self.load_and_set_thumbnail(row, data['number'])
        elif data['status'] == '下载中':
            # 显示下载中状态
            item.setText("📥 下载中...")
            item.setIcon(QIcon())
            item.setToolTip("图片正在下载中，请稍候...")
            item.setForeground(QColor("#1976d2"))
        elif data['status'] == '失败':
            # 显示详细的失败信息
            error_msg = data.get('error_msg', '生成失败')
            # 简化错误信息，保留关键部分
            if len(error_msg) > 100:
                # 截取关键错误信息
                error_msg = error_msg[:100] + "..."
            
            item.setText(f"❌ 失败:\n{error_msg}")
            item.setToolTip(data.get('error_msg', '生成失败'))  # 完整错误信息作为提示
            item.setForeground(QColor("#d32f2f"))
            item.setIcon(QIcon())  # 清除图标
        else:
            # 其他状态（等待中、生成中等）
            item.setText("")
            item.setIcon(QIcon())  # 清除图标
            item.setToolTip("")
    
    def load_and_set_thumbnail(self, row, image_number):
        """从本地文件加载并设置缩略图"""
        item = self.prompt_table.item(row, 3)
        if not item:
            return
            
        try:
            # 检查保存路径是否设置
            if not self.save_path:
                item.setText("路径未设置")
                item.setToolTip("请先在设置中心配置保存路径")
                item.setForeground(QColor("#ff9800"))
                return
            
            # 获取实际文件名
            data = self.prompt_table_data[row] if row < len(self.prompt_table_data) else None
            actual_filename = data.get('actual_filename') if data else None
            
            if actual_filename:
                # 使用保存的实际文件名
                filename = actual_filename
                file_path = os.path.join(self.save_path, filename)
            else:
                # 使用基础文件名（向后兼容）
                filename = f"{image_number}.png"
                file_path = os.path.join(self.save_path, filename)
            
            # 检查文件是否存在
            if not os.path.exists(file_path):
                item.setText("文件未找到")
                item.setToolTip(f"本地图片文件不存在: {filename}")
                item.setForeground(QColor("#ff9800"))
                return
            
            # 从本地文件加载图片
            pixmap = QPixmap(file_path)
            
            if not pixmap.isNull():
                # 缩放为缩略图大小
                thumbnail = pixmap.scaled(180, 180, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                
                # 设置图标
                item.setIcon(QIcon(thumbnail))
                item.setText("")
                item.setToolTip("双击查看大图")
                logging.info(f"缩略图加载成功: {filename}")
            else:
                item.setText("格式错误")
                item.setToolTip(f"图片格式无法识别: {filename}")
                item.setForeground(QColor("#d32f2f"))
            
        except Exception as e:
            error_msg = f"本地缩略图加载失败: {str(e)}"
            logging.error(error_msg)
            item.setText("加载失败")
            item.setToolTip(error_msg)
            item.setIcon(QIcon())  # 清除图标
            item.setForeground(QColor("#d32f2f"))
    
    def add_prompt(self):
        """添加新提示词"""
        try:
            # 生成新编号
            max_number = 0
            for data in self.prompt_table_data:
                try:
                    num = int(data['number'])
                    max_number = max(max_number, num)
                except ValueError:
                    pass
            
            new_number = str(max_number + 1)
            
            # 添加新行数据
            new_data = {
                'number': new_number,
                'prompt': '新提示词',
                'status': '等待中',
                'image_url': '',
                'error_msg': ''
            }
            
            self.prompt_table_data.append(new_data)
            self.refresh_prompt_table()
            self.update_prompt_stats()
            
            # 自动选中新添加的行
            new_row = len(self.prompt_table_data) - 1
            self.prompt_table.selectRow(new_row)
            
            # 使用QTimer延迟编辑，确保表格完全更新后再开始编辑
            QTimer.singleShot(100, lambda: self.edit_new_prompt_item(new_row))
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"添加提示词失败: {str(e)}")
    
    def edit_new_prompt_item(self, row):
        """延迟编辑新添加的提示词项"""
        try:
            if 0 <= row < self.prompt_table.rowCount():
                item = self.prompt_table.item(row, 1)  # 提示词列
                if item:
                    self.prompt_table.editItem(item)
        except Exception as e:
            # 如果编辑失败，不要崩溃，只是记录错误
            print(f"编辑新项失败: {str(e)}")
    
    def delete_selected_prompts(self):
        """删除选中的提示词"""
        selected_rows = set()
        for item in self.prompt_table.selectedItems():
            selected_rows.add(item.row())
        
        if not selected_rows:
            QMessageBox.warning(self, "提示", "请先选择要删除的提示词")
            return
        
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除选中的 {len(selected_rows)} 个提示词吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # 从大到小删除，避免索引变化
            for row in sorted(selected_rows, reverse=True):
                if 0 <= row < len(self.prompt_table_data):
                    del self.prompt_table_data[row]
            
            self.refresh_prompt_table()
            self.update_prompt_stats()
    
    def on_table_cell_changed(self, row, column):
        """表格单元格内容改变"""
        if 0 <= row < len(self.prompt_table_data):
            item = self.prompt_table.item(row, column)
            if item:
                if column == 0:  # 编号列
                    new_number = item.text().strip()
                    old_number = self.prompt_table_data[row]['number']
                    self.prompt_table_data[row]['number'] = new_number
                    
                    # 更新提示词编号映射
                    prompt = self.prompt_table_data[row]['prompt']
                    if prompt in self.prompt_numbers:
                        self.prompt_numbers[prompt] = new_number
                        logging.info(f"更新编号映射: {prompt} -> {new_number} (原: {old_number})")
                elif column == 1:  # 提示词列
                    old_prompt = self.prompt_table_data[row]['prompt']
                    new_prompt = item.text().strip()
                    self.prompt_table_data[row]['prompt'] = new_prompt
                    
                    # 更新提示词编号映射
                    if old_prompt in self.prompt_numbers:
                        number = self.prompt_numbers.pop(old_prompt)
                        self.prompt_numbers[new_prompt] = number
                    
                    # 设置工具提示显示完整内容
                    item.setToolTip(new_prompt)
                    
                    # 调整行高以适应新内容
                    self.prompt_table.resizeRowToContents(row)
                    
                    # 如果文本很长，确保表格能正确显示
                    if len(new_prompt) > 100:  # 长文本时强制刷新
                        self.prompt_table.viewport().update()
    
    def on_table_cell_double_clicked(self, row, column):
        """表格单元格双击"""
        if column == 1:  # 提示词列
            if 0 <= row < len(self.prompt_table_data):
                data = self.prompt_table_data[row]
                # 打开提示词编辑对话框
                dialog = PromptEditDialog(data['prompt'], data['number'], self)
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    # 用户确认保存，更新数据
                    new_text = dialog.get_text()
                    if new_text != data['prompt']:
                        # 更新内部数据
                        old_prompt = data['prompt']
                        data['prompt'] = new_text
                        
                        # 更新提示词编号映射
                        if old_prompt in self.prompt_numbers:
                            number = self.prompt_numbers.pop(old_prompt)
                            self.prompt_numbers[new_text] = number
                        
                        # 刷新表格显示
                        self.refresh_prompt_table()
        elif column == 3:  # 图片列
            if 0 <= row < len(self.prompt_table_data):
                data = self.prompt_table_data[row]
                if data['status'] == '成功':
                    # 打开图片查看对话框（从本地文件加载）
                    dialog = ImageViewDialog(data['number'], data['prompt'], self.save_path, self)
                    dialog.exec()
    
    def get_image_data_map(self):
        """获取所有图片数据映射"""
        image_data_map = {}
        for cat, links in self.category_links.items():
            for link in links:
                if link['name']:
                    image_data_map[link['name']] = link
        return image_data_map
    
    def extract_image_names(self, prompt):
        """从提示词中提取图片名称"""
        image_names = []
        all_names = []
        
        # 收集所有图片名称
        for cat_links in self.category_links.values():
            for link in cat_links:
                name = link['name'].strip()
                if name:
                    all_names.append(name)
        
        # 按长度排序，优先匹配更长的名称
        all_names.sort(key=len, reverse=True)
        
        # 找到所有能匹配的图片名称
        for name in all_names:
            if name in prompt:
                image_names.append(name)
        
        return image_names
    
    def start_generation(self):
        """开始生成图片"""
        # 检查配置
        if not self.api_key:
            QMessageBox.warning(self, "配置不完整", "请先在设置中心配置API密钥")
            return
        
        if not self.save_path:
            QMessageBox.warning(self, "配置不完整", "请先在设置中心设置保存路径")
            return
        
        # 检查是否有提示词
        if not self.prompt_table_data:
            QMessageBox.warning(self, "提示", "请先添加提示词或导入CSV文件")
            return
        
        self.save_config()
        
        # 获取提示词 - 只处理等待中的提示词
        prompts = []
        original_prompts = []
        
        # 只获取状态为'等待中'的提示词
        for data in self.prompt_table_data:
            if data.get('status', '等待中') == '等待中':
                prompts.append(data['prompt'])
                original_prompts.append(data['prompt'])
        
        # 检查是否有需要生成的提示词
        if not prompts:
            QMessageBox.information(self, "提示", "没有需要生成的新提示词！\n\n所有提示词都已生成完成或正在生成中。")
            return
            
        # 刷新表格显示
        self.refresh_prompt_table()
        
        # 添加风格提示词
        style_content = ""
        if self.custom_style_content.strip():
            style_content = self.custom_style_content.strip()
            if self.current_style and self.current_style in self.style_library:
                self.style_library[self.current_style]['usage_count'] = self.style_library[self.current_style].get('usage_count', 0) + 1
        elif self.current_style and self.current_style in self.style_library:
            style_content = self.style_library[self.current_style]['content'].strip()
            self.style_library[self.current_style]['usage_count'] = self.style_library[self.current_style].get('usage_count', 0) + 1
        

        
        # 处理每个提示词
        processed_prompts = []
        for p in prompts:
            if style_content and style_content not in p:
                p = f"{p} {style_content}"
            processed_prompts.append(p)
        
        prompts = processed_prompts
        
        # 设置计数器（保持兼容性）
        self.total_images = len(prompts)
        self.completed_images = 0
        
        # 记录开始时间（用于性能统计）
        self.generation_start_time = time.time()
        
        # 显示整体进度
        self.overall_progress_bar.setVisible(True)
        self.overall_progress_label.setText(f"🚀 异步生成 {len(prompts)} 张新图片...")
        
        # 更新进度显示
        self.update_generation_progress()
        
        # 更新按钮状态（但不禁用，允许继续添加新提示词）
        self.generate_button.setText("🚀 继续生成新增")
        
        # 记录异步性能信息
        logging.info(f"=== 异步生成开始 ===")
        logging.info(f"并发任务数: {self.max_concurrent_tasks}")
        logging.info(f"待生成图片数: {len(prompts)}")
        logging.info(f"预计性能提升: {min(len(prompts), self.max_concurrent_tasks)}x")
        
        # 获取图片数据映射
        image_data_map = self.get_image_data_map()
        
        # 为每个提示词创建异步任务
        for i, prompt in enumerate(prompts):
            # 从提示词中提取图片名称
            image_names = self.extract_image_names(prompt)
            
            # 获取对应的图片数据
            image_data_list = []
            for name in image_names:
                if name in image_data_map:
                    image_data_list.append(image_data_map[name])
            
            # 获取对应的编号
            original_prompt = original_prompts[i]
            # 从prompt_table_data中获取最新的编号
            if i < len(self.prompt_table_data):
                number = self.prompt_table_data[i]['number']
            else:
                number = self.prompt_numbers.get(original_prompt, str(i + 1))
            
            # 创建异步任务
            self.run_async_worker(prompt, image_data_list, number, i, original_prompt)
    
    def start_regenerate_selected(self):
        """重新生成选中的提示词"""
        # 获取选中的行
        selected_rows = set()
        for item in self.prompt_table.selectedItems():
            selected_rows.add(item.row())
        
        if not selected_rows:
            QMessageBox.warning(self, "提示", "请先选择要重新生成的提示词")
            return
        
        # 确认操作
        selected_count = len(selected_rows)
        reply = QMessageBox.question(
            self, 
            "确认重新生成", 
            f"确定要重新生成选中的 {selected_count} 个提示词吗？\n\n这将重置选中提示词的状态并重新开始生成。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # 检查配置
        if not self.api_key:
            QMessageBox.warning(self, "配置不完整", "请先在设置中心配置API密钥")
            return
        
        if not self.save_path:
            QMessageBox.warning(self, "配置不完整", "请先在设置中心设置保存路径")
            return
        
        self.save_config()
        
        # 获取选中的提示词数据
        selected_prompts = []
        selected_original_prompts = []
        
        # 按行号排序，确保顺序一致
        for row in sorted(selected_rows):
            if row < len(self.prompt_table_data):
                data = self.prompt_table_data[row]
                selected_prompts.append(data['prompt'])
                selected_original_prompts.append(data['prompt'])
                
                # 重置选中提示词的状态
                data['status'] = '等待中'
                data['image_url'] = ''
                data['error_msg'] = ''
        
        if not selected_prompts:
            QMessageBox.warning(self, "错误", "没有找到有效的提示词数据")
            return
        
        # 刷新表格显示
        self.refresh_prompt_table()
        
        # 添加风格提示词
        style_content = ""
        if self.custom_style_content.strip():
            style_content = self.custom_style_content.strip()
            if self.current_style and self.current_style in self.style_library:
                self.style_library[self.current_style]['usage_count'] = self.style_library[self.current_style].get('usage_count', 0) + 1
        elif self.current_style and self.current_style in self.style_library:
            style_content = self.style_library[self.current_style]['content'].strip()
            self.style_library[self.current_style]['usage_count'] = self.style_library[self.current_style].get('usage_count', 0) + 1
        

        
        # 处理每个提示词
        processed_prompts = []
        for p in selected_prompts:
            if style_content and style_content not in p:
                p = f"{p} {style_content}"
            processed_prompts.append(p)
        
        selected_prompts = processed_prompts
        
        # 设置计数器
        self.total_images = len(selected_prompts)
        self.completed_images = 0
        
        # 记录开始时间（用于性能统计）
        self.generation_start_time = time.time()
        
        # 显示整体进度
        self.overall_progress_bar.setVisible(True)
        self.overall_progress_label.setText(f"🔄 重新生成选中的 {len(selected_prompts)} 张图片...")
        
        # 更新进度显示
        self.update_generation_progress()
        
        # 更新按钮状态
        self.regenerate_selected_button.setText("🔄 生成中...")
        self.regenerate_selected_button.setEnabled(False)
        
        # 记录异步性能信息
        logging.info(f"=== 重新生成选中项开始 ===")
        logging.info(f"并发任务数: {self.max_concurrent_tasks}")
        logging.info(f"选中图片数: {len(selected_prompts)}")
        logging.info(f"预计性能提升: {min(len(selected_prompts), self.max_concurrent_tasks)}x")
        
        # 获取图片数据映射
        image_data_map = self.get_image_data_map()
        
        # 为每个选中的提示词创建异步任务
        for i, prompt in enumerate(selected_prompts):
            # 从提示词中提取图片名称
            image_names = self.extract_image_names(prompt)
            
            # 获取对应的图片数据
            image_data_list = []
            for name in image_names:
                if name in image_data_map:
                    image_data_list.append(image_data_map[name])
            
            # 获取对应的编号
            original_prompt = selected_original_prompts[i]
            # 从prompt_table_data中获取正确的编号
            row_index = sorted(selected_rows)[i]
            if row_index < len(self.prompt_table_data):
                number = self.prompt_table_data[row_index]['number']
            else:
                number = self.prompt_numbers.get(original_prompt, str(row_index + 1))
            
            # 创建异步任务
            self.run_async_worker(prompt, image_data_list, number, sorted(selected_rows)[i], original_prompt)
    
    def start_regenerate_all(self):
        """重新生成全部提示词"""
        # 确认操作
        reply = QMessageBox.question(
            self, 
            "确认重新生成", 
            "确定要重新生成全部提示词吗？\n\n这将重置所有状态并重新开始生成。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # 检查配置
        if not self.api_key:
            QMessageBox.warning(self, "配置不完整", "请先在设置中心配置API密钥")
            return
        
        if not self.save_path:
            QMessageBox.warning(self, "配置不完整", "请先在设置中心设置保存路径")
            return
        
        # 检查是否有提示词
        if not self.prompt_table_data:
            QMessageBox.warning(self, "提示", "请先添加提示词或导入CSV文件")
            return
        
        self.save_config()
        
        # 获取所有提示词并重置状态
        prompts = []
        original_prompts = []
        
        # 重置所有状态
        for data in self.prompt_table_data:
            data['status'] = '等待中'
            data['image_url'] = ''
            data['error_msg'] = ''
            prompts.append(data['prompt'])
            original_prompts.append(data['prompt'])
            
        # 刷新表格显示
        self.refresh_prompt_table()
        
        # 添加风格提示词
        style_content = ""
        if self.custom_style_content.strip():
            style_content = self.custom_style_content.strip()
            if self.current_style and self.current_style in self.style_library:
                self.style_library[self.current_style]['usage_count'] = self.style_library[self.current_style].get('usage_count', 0) + 1
        elif self.current_style and self.current_style in self.style_library:
            style_content = self.style_library[self.current_style]['content'].strip()
            self.style_library[self.current_style]['usage_count'] = self.style_library[self.current_style].get('usage_count', 0) + 1
        

        
        # 处理每个提示词
        processed_prompts = []
        for p in prompts:
            if style_content and style_content not in p:
                p = f"{p} {style_content}"
            processed_prompts.append(p)
        
        prompts = processed_prompts
        
        # 设置计数器（保持兼容性）
        self.total_images = len(prompts)
        self.completed_images = 0
        
        # 显示整体进度
        self.overall_progress_bar.setVisible(True)
        self.overall_progress_label.setText(f"开始重新生成 {len(prompts)} 张图片...")
        
        # 更新进度显示
        self.update_generation_progress()
        
        # 重新生成全部时禁用按钮（避免冲突）
        self.generate_button.setEnabled(False)
        self.generate_button.setText("⏸️ 重新生成中...")
        self.regenerate_all_button.setEnabled(False)
        self.regenerate_all_button.setText("🔄 重新生成中...")
        
        # 获取图片数据映射
        image_data_map = self.get_image_data_map()
        
        # 为每个提示词创建工作线程
        for i, prompt in enumerate(prompts):
            # 从提示词中提取图片名称
            image_names = self.extract_image_names(prompt)
            
            # 获取对应的图片数据
            image_data_list = []
            for name in image_names:
                if name in image_data_map:
                    image_data_list.append(image_data_map[name])
            
            # 获取对应的编号
            original_prompt = original_prompts[i]
            # 从prompt_table_data中获取最新的编号
            if i < len(self.prompt_table_data):
                number = self.prompt_table_data[i]['number']
            else:
                number = self.prompt_numbers.get(original_prompt, str(i + 1))
            
            # 创建异步任务
            self.run_async_worker(prompt, image_data_list, number, i, original_prompt)
    
    def handle_progress(self, prompt, status, original_prompt):
        """处理进度更新"""
        # 找到对应的数据行
        for data in self.prompt_table_data:
            if data['prompt'] == original_prompt:
                if "重试" in status:
                    data['status'] = status
                else:
                    data['status'] = '生成中'
                break
        
        # 刷新表格显示
        self.refresh_prompt_table()
    
    def handle_success(self, prompt, image_url, number, index, original_prompt):
        """处理成功"""
        # 找到对应的数据行并更新为下载中状态
        actual_number = number  # 默认使用传入的编号
        found = False
        for data in self.prompt_table_data:
            if data['prompt'] == original_prompt:
                data['status'] = '下载中'
                data['image_url'] = image_url
                data['error_msg'] = ''
                actual_number = data['number']  # 使用表格中的编号
                found = True
                break
        
        # 存储图片信息
        self.generated_images[prompt] = image_url
        
        # 刷新表格显示（显示下载中状态）
        self.refresh_prompt_table()
        
        # 检查是否为已保存的本地文件路径（base64格式图片）
        if os.path.exists(image_url):
            # 这是已保存的本地文件，直接标记为完成
            logging.info(f"图片已保存到本地: {image_url}")
            self.mark_download_complete(original_prompt, image_url)
        elif self.save_path:
            # 这是URL格式，需要下载
            asyncio.create_task(self.download_image_async(image_url, actual_number, original_prompt))
        else:
            # 如果没有保存路径，直接设为成功
            self.mark_download_complete(original_prompt)
        
        # 动态计算当前任务状态
        self.update_generation_progress()
        
        # 检查是否当前批次全部完成
        self.check_generation_completion()
    
    def get_unique_filename(self, number, save_path):
        """生成不重复的文件名"""
        base_filename = f"{number}.png"
        base_path = os.path.join(save_path, base_filename)
        
        # 如果文件不存在，直接使用基础文件名
        if not os.path.exists(base_path):
            return base_filename
        
        # 如果文件存在，添加后缀直到找到不重复的名称
        counter = 2
        while True:
            new_filename = f"{number}-{counter}.png"
            new_path = os.path.join(save_path, new_filename)
            if not os.path.exists(new_path):
                return new_filename
            counter += 1
    
    async def download_image_async(self, image_url, number, original_prompt):
        """异步下载图片到本地"""
        try:
            # 确保保存目录存在
            os.makedirs(self.save_path, exist_ok=True)
            
            # 生成不重复的文件名
            filename = self.get_unique_filename(number, self.save_path)
            file_path = os.path.join(self.save_path, filename)
            
            # 使用aiohttp异步下载图片
            ssl_context = setup_ssl_context()
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            timeout = aiohttp.ClientTimeout(total=300)  # 5分钟超时
            
            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                async with session.get(image_url) as response:
                    if response.status == 200:
                        # 使用aiofiles异步写入文件
                        import aiofiles
                        async with aiofiles.open(file_path, 'wb') as f:
                            async for chunk in response.content.iter_chunked(8192):
                                await f.write(chunk)
                        
                        logging.info(f"图片下载成功: {filename}")
                        logging.info(f"准备调用mark_download_complete，参数: {original_prompt}, 实际文件名: {filename}")
                        
                        # 使用信号机制通知主线程，传递实际文件名
                        try:
                            self.mark_download_complete(original_prompt, filename)
                            logging.info(f"直接调用mark_download_complete成功")
                        except Exception as e:
                            logging.error(f"直接调用mark_download_complete失败: {e}")
                    else:
                        logging.error(f"图片下载失败 - HTTP {response.status}: {image_url}")
                        QTimer.singleShot(0, lambda: self.mark_download_failed(original_prompt, f"HTTP {response.status}"))
                        
        except Exception as e:
            error_msg = f"保存图片失败: {str(e)}"
            logging.error(error_msg)
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.mark_download_failed(original_prompt, error_msg))
    
    def find_actual_image_file(self, image_number, save_path):
        """查找实际的图片文件名"""
        import os
        
        # 只查找基础文件名
        base_filename = f"{image_number}.png"
        base_file_path = os.path.join(save_path, base_filename)
        
        # 检查基础文件名是否存在
        if os.path.exists(base_file_path):
            return base_filename
        
        return None
    

    def mark_download_complete(self, original_prompt, actual_filename=None):
        """标记下载完成"""
        logging.info(f"mark_download_complete被调用，参数: {original_prompt}, 实际文件名: {actual_filename}")
        found = False
        for data in self.prompt_table_data:
            if data['prompt'] == original_prompt:
                logging.info(f"找到匹配的提示词，更新状态为成功")
                data['status'] = '成功'
                # 保存实际文件名用于缩略图加载
                if actual_filename:
                    data['actual_filename'] = actual_filename
                found = True
                break
        if not found:
            logging.warning(f"未找到匹配的提示词: {original_prompt}")
            logging.info(f"当前表格中的提示词: {[data['prompt'] for data in self.prompt_table_data]}")
        self.refresh_prompt_table()
        self.update_generation_progress()
        self.check_generation_completion()
    
    def mark_download_failed(self, original_prompt, error_msg):
        """标记下载失败"""
        for data in self.prompt_table_data:
            if data['prompt'] == original_prompt:
                data['status'] = '失败'
                data['error_msg'] = f"下载失败: {error_msg}"
                break
        self.refresh_prompt_table()
        self.update_generation_progress()
        self.check_generation_completion()
    
    def refresh_thumbnail_for_number(self, number):
        """刷新指定编号的缩略图显示"""
        for row, data in enumerate(self.prompt_table_data):
            if data['number'] == number and data['status'] == '成功':
                self.load_and_set_thumbnail(row, number)
                break
    

    
    def refresh_table_after_download(self, number):
        """图片下载完成后刷新表格显示"""
        logging.info(f"开始刷新编号 {number} 的表格显示")
        
        # 找到对应的行并刷新整行
        for row, data in enumerate(self.prompt_table_data):
            if str(data['number']) == str(number):
                logging.info(f"找到对应行 {row}，状态: {data['status']}")
                if data['status'] == '成功':
                    # 刷新图片显示
                    self.update_image_display(row, data)
                break
    
    def handle_error(self, prompt, error, index, original_prompt):
        """处理错误"""
        # 找到对应的数据行并更新
        for data in self.prompt_table_data:
            if data['prompt'] == original_prompt:
                data['status'] = '失败'
                data['image_url'] = ''
                data['error_msg'] = error
                break
        
        # 刷新表格显示
        self.refresh_prompt_table()
        
        # 记录错误
        logging.error(f"生成图片 {index+1} 失败:")
        logging.error(f"提示词: {prompt}")
        logging.error(f"错误信息: {error}")
        
        # 动态计算当前任务状态
        self.update_generation_progress()
        
        # 检查是否当前批次全部完成
        self.check_generation_completion()
    
    def update_generation_progress(self):
        """动态更新生成进度"""
        # 统计各种状态的任务数量
        waiting_count = len([data for data in self.prompt_table_data if data.get('status', '等待中') == '等待中'])
        generating_count = len([data for data in self.prompt_table_data if data.get('status', '') == '生成中' or '重试' in data.get('status', '')])
        success_count = len([data for data in self.prompt_table_data if data.get('status', '') == '成功'])
        failed_count = len([data for data in self.prompt_table_data if data.get('status', '') == '失败'])
        
        total_tasks = len(self.prompt_table_data)
        completed_tasks = success_count + failed_count
        
        # 更新进度条
        if total_tasks > 0:
            self.overall_progress_bar.setMaximum(total_tasks)
            self.overall_progress_bar.setValue(completed_tasks)
            
            # 更新进度标签
            if generating_count > 0:
                self.overall_progress_label.setText(f"进行中: 等待{waiting_count}个 | 生成中{generating_count}个 | 已完成{success_count}个 | 失败{failed_count}个")
            else:
                self.overall_progress_label.setText(f"已处理 {completed_tasks}/{total_tasks} 个任务 | 成功{success_count}个 | 失败{failed_count}个")
    
    def check_generation_completion(self):
        """检查生成是否完成"""
        # 检查是否还有正在生成或等待中的任务
        active_tasks = [data for data in self.prompt_table_data 
                       if data.get('status', '等待中') in ['等待中', '生成中', '下载中'] or '重试' in data.get('status', '')]
        
        # 如果没有活跃任务，说明当前批次已完成
        if not active_tasks:
            # 检查是否有任何按钮处于禁用状态（说明有生成任务在进行）
            if (not self.generate_button.isEnabled() or 
                not self.regenerate_selected_button.isEnabled() or 
                not self.regenerate_all_button.isEnabled()):
                self.generation_finished()
    
    def generation_finished(self):
        """生成完成"""
        self.generate_button.setEnabled(True)
        self.generate_button.setText("🚀 智能生成(仅新增)")
        self.regenerate_selected_button.setEnabled(True)
        self.regenerate_selected_button.setText("🔄 重新生成选中")
        self.regenerate_all_button.setEnabled(True)
        self.regenerate_all_button.setText("🔄 重新生成全部")
        
        # 计算性能统计
        if hasattr(self, 'generation_start_time'):
            total_time = time.time() - self.generation_start_time
            avg_time = total_time / max(self.completed_images, 1)
            
            # 记录异步性能日志
            logging.info(f"=== 异步生成完成 ===")
            logging.info(f"总耗时: {total_time:.2f}秒")
            logging.info(f"平均每张: {avg_time:.2f}秒")
            logging.info(f"并发任务数: {self.max_concurrent_tasks}")
            logging.info(f"理论加速比: {min(self.total_images, self.max_concurrent_tasks)}x")
        
        # 统计结果
        success_count = len([data for data in self.prompt_table_data if data['status'] == '成功'])
        failed_count = self.total_images - success_count
        
        # 更新状态显示
        self.overall_progress_label.setText(f"🎉 生成完成！成功: {success_count} 张，失败: {failed_count} 张")
        
        # 播放完成提示音
        self.play_completion_sound()
    
    def check_default_config(self):
        """检查并创建默认配置文件"""
        config_path = APP_PATH / 'config.json'
        if not config_path.exists():
            default_config = {
                'api_key': '',
                'api_platform': '云雾',
                'thread_count': 5,
                'retry_count': 3,
                'save_path': '',
                'style_library': {},
                'current_style': '',
                'custom_style_content': '',
                'window_geometry': {
                    'width': 1200,
                    'height': 800,
                    'x': 100,
                    'y': 100
                },
                'category_links': {},
                'key_library': {},
                'current_key_name': ''
            }
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=2, ensure_ascii=False)
    
    def load_config(self):
        """加载配置"""
        try:
            config_path = APP_PATH / 'config.json'
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                self.api_key = config.get('api_key', '')
                self.api_platform = config.get('api_platform', '云雾')
                self.thread_count = config.get('thread_count', 5)
                self.retry_count = config.get('retry_count', 3)
                self.save_path = config.get('save_path', '')
                
                # 加载风格库
                self.style_library = config.get('style_library', {})
                self.current_style = config.get('current_style', '')
                self.custom_style_content = config.get('custom_style_content', '')
                
                # 加载图片分类链接
                self.category_links = config.get('category_links', {})
                
                # 加载密钥库
                self.key_library = config.get('key_library', {})
                self.current_key_name = config.get('current_key_name', '')
                
                # 恢复窗口大小和位置
                window_geometry = config.get('window_geometry', {})
                if window_geometry:
                    width = window_geometry.get('width', 1200)
                    height = window_geometry.get('height', 800)
                    x = window_geometry.get('x', 100)
                    y = window_geometry.get('y', 100)
                    
                    self.resize(width, height)
                    self.move(x, y)
                
                # 刷新界面显示
                self.refresh_ui_after_settings()

        except FileNotFoundError:
            # 即使没有配置文件，也要刷新UI
            self.refresh_ui_after_settings()
        except Exception as e:
            # 即使配置加载失败，也要刷新UI
            self.refresh_ui_after_settings()
    
    def save_config(self):
        """保存配置"""
        if not self._init_done:
            return
        try:
            config = {
                'api_key': self.api_key,
                'api_platform': self.api_platform,
                'thread_count': self.thread_count,
                'retry_count': self.retry_count,
                'save_path': self.save_path,
                'style_library': self.style_library,
                'current_style': self.current_style,
                'custom_style_content': self.custom_style_content,
                'window_geometry': {
                    'width': self.width(),
                    'height': self.height(),
                    'x': self.x(),
                    'y': self.y()
                },
                'category_links': self.category_links,
                'key_library': self.key_library,
                'current_key_name': self.current_key_name
            }
            config_path = APP_PATH / 'config.json'
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            pass
    
    def play_completion_sound(self):
        """播放任务完成提示音"""
        try:
            if winsound:
                # Windows系统：播放系统完成提示音
                winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
            elif subprocess:
                # 跨平台方案
                if sys.platform.startswith('darwin'):  # macOS
                    subprocess.run(['afplay', '/System/Library/Sounds/Glass.aiff'], check=False)
                elif sys.platform.startswith('linux'):  # Linux
                    subprocess.run(['aplay', '/usr/share/sounds/alsa/Front_Right.wav'], check=False)
        except Exception as e:
            # 如果播放声音失败，忽略错误
            pass
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        self.save_config()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec()) 