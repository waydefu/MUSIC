"""純邏輯層。

本套件內**不得出現任何 PySide6 import**。所有商業邏輯都放這裡，
好處是整層可以無頭跑 pytest，不需要開視窗、不需要音訊裝置。

依賴方向：``ui/qml → bridge → audio/library/platform → core``，永不反向。
``platform/`` 是平台能力的契約層，``platform_win/`` 是它底下的 Windows 實作。
"""
