"""Small editable scenario catalog; sample values never enter AI/file operations."""
from dataclasses import dataclass, replace

from .naming_fields import NamingFields
from .template_model import STANDARD_FIELDS, DateFormat, Template


@dataclass(frozen=True)
class ScenarioPreset:
    slug: str
    name: str
    chinese_name: str
    description_zh: str
    description_en: str
    fields: tuple[str, ...]
    sample: tuple[tuple[str, str], ...]
    extension: str
    expected_example: str
    date_format: DateFormat = DateFormat.YYYY_MM_DD

    @property
    def id(self) -> str:
        return f"builtin.{self.slug}.v1"

    def template(self) -> Template:
        ordered = list(self.fields) + [f.dc_name for f in STANDARD_FIELDS if f.dc_name not in self.fields]
        by_name = {f.dc_name: f for f in STANDARD_FIELDS}
        return Template(id=self.id, name=self.name,
            pattern="_".join("{" + name + "}" for name in self.fields),
            date_format=self.date_format,
            fields=tuple(replace(by_name[name], id=f"{self.id}.{name}", order=i + 1,
                enabled=name in self.fields) for i, name in enumerate(ordered)))

    def sample_fields(self, template: Template) -> NamingFields:
        values = {
            "dcTitle": "产品使用说明", "dcSubject": "学习", "dcType": "资料",
            "dcCreator": "张三", "dcIdentifier": "DOC-001", "extOrganization": "星河公司",
            "extProject": "官网改版", "extStatus": "已确认", "extVersion": "V2",
            **dict(self.sample),
        }
        values["dcDate"] = {
            DateFormat.YYYY_MM_DD: "2026-09-08", DateFormat.YYYYMMDD: "20260908",
            DateFormat.YYYY_MM: "2026-09", DateFormat.YYYYMM: "202609",
        }[template.date_format]
        return NamingFields(**values)


SCENARIO_PRESETS = (
    ScenarioPreset("simple-title", "Simple Title", "简洁标题",
        "日常文件：只保留内容标题，去掉杂乱原名。", "Everyday files: keep only a meaningful content title.",
        ("dcTitle",), (("dcTitle", "产品使用说明"),), ".pdf", "产品使用说明.pdf"),
    ScenarioPreset("receipts", "Receipts and Expenses", "票据报销",
        "发票、收据、报销凭证：日期＋类型＋标题。", "Invoices and receipts: date, document type and title.",
        ("dcDate", "dcType", "dcTitle"), (("dcType", "发票"), ("dcTitle", "办公用品")),
        ".pdf", "2026-09-08_发票_办公用品.pdf"),
    ScenarioPreset("contracts", "Contracts", "合同往来",
        "合同、协议：公司＋日期＋标题；需要可识别的公司名称。", "Agreements: organization, date and title. Requires an identifiable organization.",
        ("extOrganization", "dcDate", "dcTitle"), (("dcTitle", "采购合同"),),
        ".pdf", "星河公司_2026-09-08_采购合同.pdf"),
    ScenarioPreset("projects", "Project Documents", "项目资料",
        "方案、需求、交付材料：项目＋日期＋标题；需要项目名称。", "Plans and deliverables: project, date and title. Requires a project name.",
        ("extProject", "dcDate", "dcTitle"), (("dcTitle", "需求说明"),),
        ".docx", "官网改版_2026-09-08_需求说明.docx"),
    ScenarioPreset("study", "Study Materials", "学习资料",
        "课程讲义、学习笔记：主题＋标题，方便按学习内容查找。", "Lecture notes and study material: subject and title.",
        ("dcSubject", "dcTitle"), (("dcSubject", "英语学习"), ("dcTitle", "阅读笔记")),
        ".pdf", "英语学习_阅读笔记.pdf"),
    ScenarioPreset("papers", "Research Papers", "论文文献",
        "论文、研究资料：作者＋年月＋标题；需要作者和日期。", "Research: creator, year-month and title. Requires creator and date.",
        ("dcCreator", "dcDate", "dcTitle"), (("dcTitle", "图像识别研究"),),
        ".pdf", "张三_2026-09_图像识别研究.pdf", DateFormat.YYYY_MM),
    ScenarioPreset("media", "Photos and Videos", "照片与视频",
        "照片、视频素材：主题＋日期＋内容标题；画面识别需要支持图片的模型。", "Media: subject, date and title. Visual recognition requires an image-capable model.",
        ("dcSubject", "dcDate", "dcTitle"), (("dcSubject", "旅行"), ("dcTitle", "海边日落")),
        ".jpg", "旅行_2026-09-08_海边日落.jpg"),
    ScenarioPreset("versions", "Versioned Documents", "版本文档",
        "迭代文件：项目＋标题＋版本号；需要明确的项目和版本信息。", "Revisions: project, title and version. Requires explicit project and version details.",
        ("extProject", "dcTitle", "extVersion"), (("dcTitle", "设计方案"),),
        ".docx", "官网改版_设计方案_V2.docx"),
)

PRESETS_BY_ID = {preset.id: preset for preset in SCENARIO_PRESETS}
