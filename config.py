import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///disaster_management.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # 高德地图配置
    AMAP_KEY = os.environ.get('AMAP_KEY') or ''
    AMAP_SECURITY_CODE = os.environ.get('AMAP_SECURITY_CODE') or ''
    
    # 生产环境域名配置
    SERVER_NAME = os.environ.get('SERVER_NAME')  # 在生产环境设置为 xxx.com 
