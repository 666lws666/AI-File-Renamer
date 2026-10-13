"""Display-only HK labels for unmodified built-ins; never rewrite user data."""

DEFAULT_NAME = "通用命名（預設）"
DEFAULT_DESCRIPTION = "日常檔案：日期＋標題；不確定選哪個時，可先用這個。"
CUSTOM_DESCRIPTION = "按目前欄位規則命名；可編輯欄位及排列次序。"

# Stable slug -> (name, purpose).
PRESET_LABELS = {
    "simple-title": ("簡潔標題", "日常檔案：只保留內容標題，移除雜亂的原名稱。"),
    "receipts": ("單據報銷", "發票、收據及報銷憑證：日期＋類型＋標題。"),
    "contracts": ("合約往來", "合約、協議：公司＋日期＋標題；需要可識別的公司名稱。"),
    "projects": ("項目資料", "方案、需求及交付資料：項目＋日期＋標題；需要項目名稱。"),
    "study": ("學習資料", "課程講義及學習筆記：主題＋標題，方便按內容尋找。"),
    "papers": ("論文文獻", "論文及研究資料：作者＋年月＋標題；需要作者及日期。"),
    "media": ("相片與影片", "相片及影片素材：主題＋日期＋內容標題；畫面識別需要支援圖片的模型。"),
    "versions": ("版本文件", "修訂檔案：項目＋標題＋版本號；需要明確的項目及版本資料。"),
}
