# 人效计算工具

一个本地运行的人效统计小工具，用于从飞书表格抓取作业完成数据，维护人员名单和工时，并按两个快照之间的增量计算人效。

## 适合谁用

- 需要定期从飞书表格统计作业完成量的人
- 需要按人员、公司、工时计算「件/小时」的人效看板的人
- 希望数据和飞书凭证只保存在本机、不部署服务器的人

## 主要功能

| 页面 | 功能 |
| --- | --- |
| 快照管理 | 粘贴飞书表格或知识库链接，抓取当前作业完成数据并保存为快照 |
| 人员名单 | 维护参与计算的人员、公司和默认工时 |
| 填写工时 | 按人员和公司快速调整工时 |
| 人效看板 | 选择起始快照和结束快照，计算作业增量、工时和人效 |
| 飞书配置 | 保存并验证飞书自建应用的 App ID 和 App Secret |

## Windows 用户直接使用

1. 在 GitHub Release 下载 `efficiency-app.exe`。
2. 放到一个固定文件夹里，例如 `D:\人效计算工具\`。
3. 双击运行 `efficiency-app.exe`。
4. 程序会启动本地服务，并自动打开浏览器页面。
5. 首次使用进入「飞书配置」，填写飞书自建应用的 `App ID` 和 `App Secret`。

程序不会上传你的本地数据。运行后会在 exe 同目录生成：

- `efficiency.db`：本地 SQLite 数据库，保存快照、人员名单和工时
- `feishu_config.json`：飞书应用凭证和 token 缓存

如果要把工具迁移到另一台电脑，可以把 exe、`efficiency.db` 和 `feishu_config.json` 一起复制过去。

## 飞书应用准备

1. 打开飞书开放平台，创建「企业自建应用」。
2. 获取应用的 `App ID` 和 `App Secret`。
3. 给应用开通表格相关权限，并发布/启用应用。
4. 把这个自建应用添加为目标飞书表格的协作者，确保它有读取权限。
5. 如果需要导出看板到飞书表格，还需要给目标表格编辑权限。

常见问题：

- 提示「请先配置飞书应用凭证」：进入「飞书配置」保存凭证。
- 提示权限不足：检查应用权限、应用是否发布、应用是否是表格协作者。
- 抓取为空：确认表头名称包含一轮/二轮领取人和完成状态字段，且表格数据结构没有大幅变更。

## 本地源码运行

需要 Python 3.11 或更高版本。

```bash
pip install -r requirements.txt
python app.py
```

默认访问地址是：

```text
http://127.0.0.1:5000
```

如果 `5000` 端口已被占用，程序会自动使用下一个可用端口。

## 打包 exe

在 Windows 上执行：

```bash
pyinstaller --noconfirm --clean --onefile --windowed --name 人效计算 --add-data "templates;templates" --add-data "static;static" app.py
```

打包完成后，exe 位于：

```text
dist\efficiency-app.exe
```

## 数据安全说明

- 本工具只在本机运行 Flask 服务。
- 飞书凭证保存到本地 `feishu_config.json`。
- 业务数据保存到本地 `efficiency.db`。
- `.gitignore` 已排除数据库、凭证、构建产物和缓存文件，避免误提交。

## 开发验证

```bash
python -X utf8 tests\test_app.py
python -m py_compile app.py feishu_api.py feishu_auth.py lark_reader.py models.py desktop_app.py
```

## 技术栈

- Flask
- SQLite
- 飞书开放平台 API
- PyInstaller
