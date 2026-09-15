# 馆藏标签恢复 API

OCR 识别磨损的馆藏标签时，常在相似字形之间给出多个候选。本服务利用标签
自身的编码规则，从候选中恢复出**唯一、可复核**的编码，供入藏系统继续
关联实物，全程无需人工挑选。

## 编码规则

编码共 10 位：

| 位置 | 含义 | 字符类别 |
| ---- | ---- | ---- |
| 0–1 | 前缀 | 大写字母 `A-Z` |
| 2–8 | 七个数据数字 | 数字 `0-9` |
| 9 | 校验数字 | 数字 `0-9` |

校验式：七个数据数字从左到右分别乘 **3、1、7、3、1、7、3**，乘积之和
对 10 取余即为末位。例如数据数字 `1 3 5 6 7 8 9` 的加权和为
`3+3+35+18+7+56+27 = 149`，`149 % 10 = 9`，故完整编码以 `9` 结尾。

## 恢复规则

- 服务穷举前九位的全部候选组合（每处至多 3 个候选，搜索空间最大
  3⁹ = 19683），仅保留校验位落在第 9 位候选集合中的组合；
- 以所选候选置信度之和**降序**取胜；同分时取完整编码**字典序最小**者；
- 结果只取决于候选集合本身，与候选在请求中的排列次序无关——同一批
  候选无论输入顺序如何，都会得到同一个唯一标签；
- 没有任何合法组合时返回 `422`。

## 模块划分

| 模块 | 职责 |
| ---- | ---- |
| `app/schemas.py` | 请求约束（Pydantic）：十个位置、每处 1–3 个不重复候选、置信度 0–100 整数、逐位字符类别 |
| `app/solver.py` | 搜索：穷举候选组合并筛出合法标签 |
| `app/checksum.py` | 校验与排序：校验式、编码格式检查、排名键（总分降序、编码字典序） |
| `app/response.py` | 响应组装：编码、总分、逐位选择 |
| `app/errors.py` | 错误处理：422 响应统一指出位置与原因 |
| `app/main.py` | FastAPI 应用与路由 |

## API

### `POST /recover`

请求体固定包含十个位置，每处含一至三个候选：

```json
{
  "positions": [
    {"candidates": [{"char": "A", "confidence": 90}, {"char": "B", "confidence": 80}]},
    {"candidates": [{"char": "C", "confidence": 95}, {"char": "D", "confidence": 70}]},
    {"candidates": [{"char": "1", "confidence": 60}, {"char": "2", "confidence": 50}]},
    {"candidates": [{"char": "3", "confidence": 99}]},
    {"candidates": [{"char": "4", "confidence": 10}, {"char": "5", "confidence": 20}]},
    {"candidates": [{"char": "6", "confidence": 77}]},
    {"candidates": [{"char": "7", "confidence": 88}]},
    {"candidates": [{"char": "8", "confidence": 66}]},
    {"candidates": [{"char": "9", "confidence": 55}]},
    {"candidates": [{"char": "9", "confidence": 44}, {"char": "0", "confidence": 100}]}
  ]
}
```

成功响应 `200`，返回编码、总分和逐位选择：

```json
{
  "code": "AC13567899",
  "total_score": 694,
  "choices": [
    {"position": 0, "char": "A", "confidence": 90},
    {"position": 1, "char": "C", "confidence": 95},
    {"position": 2, "char": "1", "confidence": 60},
    {"position": 3, "char": "3", "confidence": 99},
    {"position": 4, "char": "5", "confidence": 20},
    {"position": 5, "char": "6", "confidence": 77},
    {"position": 6, "char": "7", "confidence": 88},
    {"position": 7, "char": "8", "confidence": 66},
    {"position": 8, "char": "9", "confidence": 55},
    {"position": 9, "char": "9", "confidence": 44}
  ]
}
```

### 错误响应 `422`

以下情况整体拒绝，错误指出位置（`position`，从 0 计）与原因（`reason`）：

- 候选位置不足十个（或超过十个）；
- 字符类别错误（前两位非大写 A-Z、其余位非数字、小写字母等）；
- 同一位置候选字符重复；
- 置信度越界（非 0–100 的整数）；
- 每处候选少于 1 个或多于 3 个；
- 所有组合均不满足格式与校验式（此时 `position` 为 `null`）。

```json
{
  "detail": [
    {"position": 5, "reason": "position 5: character 'x' is not a digit 0-9"}
  ]
}
```

### `GET /health`

健康检查，返回 `{"status": "ok"}`。

## 本地开发

需要 Python 3.12：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest                          # 运行测试
uvicorn app.main:app --reload   # 本地启动，http://127.0.0.1:8000/docs
```

## Docker

Compose 默认只运行 API，宿主端口由环境变量 `API_PORT` 覆盖（默认 8000）：

```bash
docker compose up --build                 # 宿主 8000 端口
API_PORT=9000 docker compose up --build   # 宿主 9000 端口
```

一次性验收服务 `verify` 位于独立 profile，不影响默认启动；它等待 API
健康后执行全部验收场景（合法恢复、次序无关、同分字典序、各类 422），
全部通过时以退出码 0 结束：

```bash
docker compose --profile verify up --build --abort-on-container-exit verify
```

也可以对任意运行中的实例单独执行验收：

```bash
API_BASE_URL=http://localhost:9000 python verify.py
```

## 测试

```bash
pytest
```

测试覆盖：校验式与格式检查、最优解选择、同分字典序、候选次序无关性、
高置信度诱饵校验位、无合法组合 422，以及全部请求约束的 422 行为。
