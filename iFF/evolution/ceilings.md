# iFF 天花板登记(每条必须带 probe;无 probe = NEEDS_PROBE,退回重路由)

| 设计/场景 | 天花板 | probe(证据) |
|---|---|---|
| 申请5人脸 | 原生百融活体 SDK + 相机人脸采集无法在 CI 端到端验证 | MethodChannel('nigeria_4/liveness') MissingPluginException;第三方原生插件+相机+账号+license 不在工程/模拟器;正确做法=接口抽象+fake 测,真执行在真机 |
| 申请5 / OSS 直传 | 阿里云 OSS 直传图片无法在 CI 跑 | 需 Aliyun OSS SDK + 真实 STS 凭证,环境无 |
| 全部含文字/矢量设计 | 跨引擎字形/边缘抗锯齿 → 像素 SSIM 不可达 0.99 | Impeller≠Figma,delta>3 下边缘像素~55% 翻转 ≈ 3% 地板;故视觉门改结构化,SSIM 仅诊断 |
| 全部 | 真机系统状态栏(设计烤死 9:41 vs 模拟器时钟) | IMPL-IMG-3 排除状态栏切图;像素诊断里属固定残差 |
| 无切图任意矢量精确形状 | render_plan 只有 bbox+fill,精确形状丢失 | 常见图标('<'/'v' chevron)几何兜底;其它形状需设计侧导出切图 |

> 注:R12 全屏背景图**不是**天花板——它是不变量①边界歧义(ESCALATE 待决),不是环境限制。
