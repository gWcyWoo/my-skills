---
name: icpl
description: 本地文件存储适配器。与 icps/icpd/icpf 实现相同合约(统一行格式),后端是本地 JSON 文件,用于开发测试,无需 MCP / 网络。
---

# ICPL

本地文件存储适配器。iole 工厂按本地文件路径派发到此 skill。
与 icps(Google Sheets)、icpd(钉钉)、icpf(飞书)实现相同合约。

统一行格式见 `../icps/ROW.md`。

## 动词

```
python3 scripts/icpl.py <verb> --link <file.json> --role <role> ...
```

### inspect — 查询 + 可选原子锁定

```
inspect --link <f> --role <r> --status ready              # 查第一个 ready 行
inspect --link <f> --role <r> --title 登录                # 按标题查行
inspect --link <f> --role <r> --status ready --claim doing  # 原子读+锁,返回 lease_token
```

### claim — 状态迁移(通用)

```
claim --link <f> --role <r> --row-ids r1 --status review --lease-token <t> [--pr MR-1]
claim --link <f> --role <r> --row-ids r1 --status ready --error "原因"
```

- `--status review`:完成,释放租约,可带 `--pr`
- `--status ready` + `--error`:失败回退,释放租约,记 last_error
- `--lease-token`:CAS 校验,不匹配报 `stale_lease`

### list-rows

```
list-rows --link <f> --role <r>  → [{row_id, title}]
```

`--link` 指向本地 JSON 文件路径。

## 测试

```
cd .. && python3 -m unittest icpl.tests.test_icpl
```
