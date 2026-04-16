# 安装指南

详细的环境配置和安装步骤。

## 系统要求

### 必需软件
- **Python**: 3.11 或更高版本
- **Node.js**: 18.0 或更高版本
- **Git**: 用于克隆项目
- **Conda**: 推荐使用 Anaconda 或 Miniconda

### 可选软件
- **PostgreSQL**: 生产环境推荐使用
- **Redis**: 用于缓存（可选）

## 详细安装步骤

### 1. 准备工作

#### 1.1 克隆项目
```bash
git clone <your-repo-url>
cd bilibili-rag-main
```

#### 1.2 创建Conda环境
```bash
# 创建名为bilibili的Python 3.11环境
conda create -n bilibili python=3.11

# 激活环境
conda activate bilibili
```

### 2. 后端安装

#### 2.1 安装Python依赖
```bash
# 确保在bilibili环境中
conda activate bilibili

# 安装核心依赖
pip install -r requirements.txt

# 安装DeerFlow框架
pip install -e ./backend/packages/harness
```

#### 2.2 配置环境变量
```bash
# 复制环境变量模板
cp .env.example .env

# 编辑.env文件，填入必要的API密钥
# 至少需要配置以下变量：
# - DASHSCOPE_API_KEY
# - OPENAI_API_KEY
# - LLM_MODEL
```

#### 2.3 初始化数据库
```bash
# 数据库会在首次启动时自动创建
# 也可以手动运行迁移脚本
python -c "from app.database import init_db; import asyncio; asyncio.run(init_db())"
```

### 3. 前端安装

#### 3.1 安装Node.js依赖
```bash
cd frontend

# 使用npm安装依赖
npm install

# 或使用yarn
# yarn install
```

#### 3.2 配置前端环境
```bash
# 如果需要配置前端环境变量
cp .env.example .env.local

# 编辑.env.local文件
```

### 4. 启动服务

#### 4.1 启动后端
```bash
# 在项目根目录
conda activate bilibili

# 使用绝对路径启动（推荐）
E:\anaconda\envs\bilibili\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 或使用conda环境中的python
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 开发模式（支持热重载）
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

#### 4.2 启动前端
```bash
# 在frontend目录
cd frontend

# 开发模式
npm run dev

# 生产构建
npm run build
```

### 5. 验证安装

#### 5.1 检查后端
```bash
# 访问API文档
# 浏览器打开: http://localhost:8000/docs

# 测试API
curl http://localhost:8000/api/health
```

#### 5.2 检查前端
```bash
# 浏览器打开: http://localhost:3000

# 检查控制台是否有错误
```

## 常见问题

### Python环境问题

**Q: conda activate不生效？**
```bash
# 初始化conda for CMD
conda init cmd.exe

# 重新打开CMD后再激活
conda activate bilibili
```

**Q: pip install很慢？**
```bash
# 使用国内镜像源
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

**Q: DeerFlow找不到模块？**
```bash
# 确保使用bilibili环境的Python
E:\anaconda\envs\bilibili\python.exe -m uvicorn app.main:app
```

### 依赖安装问题

**Q: 某些包安装失败？**
```bash
# 更新pip
python -m pip install --upgrade pip

# 单独安装失败的包
pip install <package_name> --no-cache-dir
```

**Q: 前端依赖冲突？**
```bash
# 删除node_modules重新安装
rm -rf node_modules package-lock.json
npm install
```

### 运行时问题

**Q: 端口被占用？**
```bash
# Windows查找占用端口的进程
netstat -ano | findstr :8000

# 结束进程
taskkill /PID <pid> /F
```

**Q: 数据库连接错误？**
```bash
# 检查数据库文件权限
ls -la data/

# 重新初始化数据库
rm data/*.db
python -c "from app.database import init_db; import asyncio; asyncio.run(init_db())"
```

## 开发环境配置

### VSCode配置
创建 `.vscode/settings.json`:
```json
{
  "python.defaultInterpreterPath": "E:\\anaconda\\envs\\bilibili\\python.exe",
  "python.lintingEnabled": true,
  "python.formattingProvider": "black",
  "editor.formatOnSave": true
}
```

### Git配置
```bash
# 设置.gitignore（如果还没有）
cp .gitignore.example .gitignore

# 配置用户信息
git config user.name "Your Name"
git config user.email "your.email@example.com"
```

## 生产环境部署

### Docker部署（推荐）
创建 `Dockerfile` 和 `docker-compose.yml`，参考部署文档。

### 传统部署
1. 使用 `gunicorn` 或 `uwsgi` 部署后端
2. 使用 `nginx` 反向代理
3. 配置HTTPS证书
4. 设置进程守护（systemd或supervisor）

详细部署指南请参考 `docs/DEPLOYMENT.md`。

## 更新和维护

### 更新依赖
```bash
# 后端依赖
pip install --upgrade -r requirements.txt

# 前端依赖
npm update
```

### 数据库迁移
```bash
# 运行数据库迁移
python scripts/migrate_db.py
```

### 日志查看
```bash
# 查看后端日志
tail -f logs/app.log

# 查看错误日志
grep ERROR logs/app.log
```

## 卸载

### 完全卸载
```bash
# 1. 停止所有服务
# 2. 删除conda环境
conda deactivate
conda env remove -n bilibili

# 3. 删除项目目录
cd ..
rm -rf bilibili-rag-main

# 4. 清理全局npm包（可选）
npm cache clean --force
```