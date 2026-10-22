import os
import sys

# 检查环境变量
USER_AGENT = os.getenv("LIQUIPEDIA_USER_AGENT")
if not USER_AGENT or "your-email@example.com" in USER_AGENT:
    print("❌ 错误：请先在终端设置真实的环境变量 LIQUIPEDIA_USER_AGENT！")
    sys.exit(1)

print("正在连接 Liquipedia 测试您的 IP 状态...")
try:
    from ggpyscraper.liquipedia_objects import tournament
    # 请求列表页（最轻量的请求）
    t = tournament.Tournament(game="counterstrike", name="HLTV/MVP_Awards", user=USER_AGENT)
    raw = t.get_raw_str()
    
    if raw:
        print("✅ 测试成功！您的网络 IP 是干净的，可以放心运行全量抓取。")
    else:
        print("❌ 测试失败：返回数据为空。")

except Exception as e:
    error_msg = str(e)
    if "429" in error_msg:
        print("❌ 测试失败：您的 IP 已被 Liquipedia 封禁（429 Too Many Requests）。")
        print("👉 建议：1. 切换手机热点；2. 更换代理节点；3. 等待 24 小时后再试。")
    else:
        print(f"❌ 测试失败，发生网络错误：{error_msg}")