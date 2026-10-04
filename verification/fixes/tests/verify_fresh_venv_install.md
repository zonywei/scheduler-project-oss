# verify_fresh_venv_install

目的：在全新虚拟环境中验证 `requirements.txt` 可安装且项目入口可导入执行。  
执行平台：Windows PowerShell

## 可复制命令

```powershell
python -m venv .venv_verify
.\.venv_verify\Scripts\python -m pip install -U pip
.\.venv_verify\Scripts\pip install -r requirements.txt
.\.venv_verify\Scripts\python -c "import ortools,pandas,openpyxl,yaml; print('imports: PASS')"
.\.venv_verify\Scripts\python run.py --help
```

## 本次实测结果（原样摘要）

### 1) `python -m venv .venv_verify`
- 结果：成功（exit code 0）

### 2) `.\.venv_verify\Scripts\python -m pip install -U pip`
```text
Requirement already satisfied: pip ... (22.0.4)
Collecting pip
Installing collected packages: pip
Successfully installed pip-26.0.1
```

### 3) `.\.venv_verify\Scripts\pip install -r requirements.txt`
```text
Collecting ortools==9.15.6755
Collecting pandas==2.3.2
Collecting openpyxl==3.1.5
Collecting PyYAML==6.0.3
...
Successfully installed PyYAML-6.0.3 ... ortools-9.15.6755 pandas-2.3.2 ...
```

### 4) `.\.venv_verify\Scripts\python -c "import ortools,pandas,openpyxl,yaml; print('imports: PASS')"`
```text
imports: PASS
```

### 5) `.\.venv_verify\Scripts\python run.py --help`
```text
usage: run.py [-h] [--mode {day,night,both,joint}] [--config CONFIG]
              [--grade GRADE] [--verbose]
...
```

## 失败时处理说明（本次未触发）

若第 3 步安装失败，请原样保留 pip 报错全文，并仅采用不改变语义的处理建议：
1. 明确支持的 Python 版本区间（例如与 wheel 可用版本对齐）。
2. 对个别平台冲突包改为兼容范围（不改业务代码）。
3. 在文档标注镜像源或网络要求，避免误判为依赖问题。
