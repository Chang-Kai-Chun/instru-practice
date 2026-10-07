import reflex as rx


config = rx.Config(
    app_name="front",
    backend_port=8001,
    # 設定後端伺服器位置在8001，才不會跟FastAPI衝突，因為FastAPI預設是8000
    # 預設的前端會在3000
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
        rx.plugins.RadixThemesPlugin(),
    ],
)
