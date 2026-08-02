# Jubensha 剧本杀管理系统

一个功能完整的剧本杀门店管理系统，包含门店、剧本、DM、预订、排期、玩家匹配、评价和审计等模块。

## 技术栈

### 后端
- **框架**: Django 4.2.7 + Django REST Framework 3.14.0
- **数据库**: MySQL 8.0
- **认证**: JWT (djangorestframework-simplejwt)
- **算法**: OR-Tools (排班与角色匹配)
- **其他**: django-filter, django-cors-headers, Pillow

## 功能模块

| 模块 | 说明 |
|------|------|
| accounts | 用户账户与权限管理 |
| stores | 门店信息管理 |
| scripts | 剧本资源管理 |
| dms | DM（主持人）管理与排班 |
| bookings | 订单预订管理 |
| scheduling | 排期与场次管理 |
| players | 玩家档案与角色智能匹配 |
| reviews | 剧本与门店评价 |
| audit | 操作审计日志 |

## 快速开始

### 方式一：Docker Compose（推荐）

```bash
# 克隆项目后，在项目根目录执行
docker-compose up -d

# 初始化管理员账号
docker-compose exec backend python manage.py init_admin
```

访问地址：
- 后端 API: http://localhost:8000

### 方式二：本地开发

#### 后端

```bash
cd backend

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp ../.env.example .env

# 数据库迁移
python manage.py migrate

# 初始化管理员
python manage.py init_admin

# 启动服务
python manage.py runserver 0.0.0.0:8000
```


## 环境变量

参考 `.env.example`：

```bash
# Django 设置
DJANGO_SECRET_KEY=your-secret-key
DEBUG=true

# 数据库配置
DB_NAME=script_killer_db
DB_USER=root
DB_PASSWORD=scriproot
DB_HOST=localhost
DB_PORT=3306

# 允许的主机
ALLOWED_HOSTS=*,localhost,127.0.0.1
```

## API 接口

所有 API 均以 `/api/` 前缀开头：

- `POST /api/auth/login/` - 登录
- `GET /api/stores/` - 门店列表
- `GET /api/scripts/` - 剧本列表
- `GET /api/dms/` - DM 列表
- `GET /api/bookings/` - 预订列表
- `GET /api/scheduling/` - 排期列表
- `GET /api/players/match/` - 角色匹配

## 许可证

MIT
