"""Python 與 QML 之間的唯一邊界。

規約：

* 這一層**只放 ViewModel** —— ``Property`` / ``Signal`` / ``Slot`` /
  ``QAbstractListModel``，把下層的值物件翻譯成 QML 綁得動的東西。
* **商業邏輯不准寫在這裡，也不准寫在 QML 裡。** 邏輯住在 ``core/``，
  I/O 住在 ``audio/`` ``library/`` ``platform/``。
* **平台能力一律走 ``aurora.platform.adapter()``**，不得直接 import
  ``platform_win`` —— 那樣做在 Windows 上完全正常，卻會讓 macOS 連
  import 都過不了。``tests/test_platform.py`` 有靜態檢查守這條。
* QML 只綁定屬性與呼叫 slot，不做判斷。

每個 ViewModel 的 signal 契約都寫在各自的 docstring 裡。
"""
