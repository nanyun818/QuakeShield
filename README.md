# 灾情管理系统

这是一个基于 Flask 的灾情管理系统，提供灾情信息的管理、分析和可视化功能。

## 功能模块

1. 用户交互模块
2. 灾情分析与可视化模块
3. 房屋安全性评估模块
4. 灾前灾后对比模块
5. 地图展示模块

## 系统要求

- Python 3.7+
- Flask 3.0.0
- Flask-Login 0.6.3
- Werkzeug 3.0.1

## 安装步骤

1. 创建虚拟环境（推荐）：
```bash
python -m venv venv
```

2. 激活虚拟环境：
- Windows:
```bash
venv\Scripts\activate
```
- Linux/Mac:
```bash
source venv/bin/activate
```

3. 安装依赖：
```bash
pip install -r requirements.txt
```

## 运行系统

1. 激活虚拟环境（如果尚未激活）

2. 运行 Flask 应用：
```bash
python app.py
```



## 默认登录信息

- 用户名：admin
- 密码：admin

## 目录结构

```
.
├── app.py              # 主应用文件
├── requirements.txt    # 项目依赖
├── README.md          # 项目说明文档
└── templates/         # HTML 模板文件
    ├── base.html     # 基础模板
    ├── login.html    # 登录页面
    ├── dashboard.html # 主面板
    └── ...           # 其他模块模板
```

## 开发说明

- 本系统使用 Flask 作为后端框架
- 前端使用原生 HTML、CSS 实现
- 使用 Flask-Login 处理用户认证
- 所有模板都继承自 `base.html`

## 注意事项

- 这是一个演示系统，生产环境中请务必修改默认密码
- 确保在生产环境中使用安全的密钥
- 建议添加适当的日志记录和错误处理机制 
