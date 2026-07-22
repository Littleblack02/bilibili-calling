"""Generate reviewed Ontology V2 Turtle modules from a compact curated catalog."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology"
VERSION = "2.0.0"


def C(identifier, label, parent, aliases=(), kind="Topic"):
    return (identifier, label, parent, tuple(aliases), kind)


CORE = [
    C("Tutorial", "教程", None, ("tutorial", "入门教程"), "ContentFormat"),
    C("HandsOn", "实战", None, ("hands-on", "项目实战"), "ContentFormat"),
    C("Review", "测评", None, ("review", "评测"), "ContentFormat"),
    C("News", "资讯", None, ("news", "新闻"), "ContentFormat"),
    C("DocumentaryFormat", "纪录片形式", None, ("documentary format",), "ContentFormat"),
    C("Commentary", "解说", None, ("commentary",), "ContentFormat"),
    C("Vlog", "视频日志", None, ("Vlog",), "ContentFormat"),
    C("LiveReplay", "直播回放", None, ("录播",), "ContentFormat"),
    C("Beginner", "入门", None, ("beginner", "零基础"), "Difficulty"),
    C("Intermediate", "进阶", None, ("intermediate", "中级"), "Difficulty"),
    C("Advanced", "高级", None, ("advanced", "深入"), "Difficulty"),
]


TAXONOMY = [
    ("Technology", "科技", 188, ("technology", "数码科技")),
    ("Knowledge", "知识", 36, ("knowledge", "泛知识")),
    ("Animation", "动画", 1, ("animation", "动漫作品")),
    ("Game", "游戏", 4, ("gaming", "电子游戏")),
    ("Music", "音乐", 3, ("music", "音乐内容")),
    ("Film", "影视", 181, ("film and television", "影视内容")),
    ("Life", "生活", 160, ("lifestyle", "生活记录")),
    ("Entertainment", "娱乐", 5, ("entertainment", "娱乐内容")),
    ("Sports", "运动", 234, ("sports", "体育运动")),
    ("Food", "美食", 211, ("food", "烹饪美食")),
    ("Dance", "舞蹈", 129, ("dance",)),
    ("Fashion", "时尚", 155, ("fashion",)),
    ("Automotive", "汽车", 223, ("automotive",)),
    ("Animals", "动物圈", 217, ("animals", "萌宠")),
    ("Information", "资讯分区", 202, ("information",)),
    ("Kichiku", "鬼畜", 119, ("kichiku",)),
    ("TVShow", "综艺", 71, ("Bilibili variety partition",)),
    ("Documentary", "纪录片", 177, ("documentary",)),
    ("Movie", "电影", 23, ("movie",)),
    ("Teleplay", "电视剧", 11, ("teleplay", "TV drama")),
]


MODULES = {
    "domains/ai.ttl": [
        C("ArtificialIntelligence", "人工智能", "Technology", ("AI",)),
        C("MachineLearning", "机器学习", "ArtificialIntelligence", ("ML",)),
        C("DeepLearning", "深度学习", "MachineLearning", ("DL",)),
        C("GenerativeAI", "生成式人工智能", "ArtificialIntelligence", ("生成式AI", "AIGC", "Generative AI")),
        C("LargeLanguageModel", "大语言模型", "GenerativeAI", ("大模型", "LLM", "Large Language Model")),
        C("Transformer", "Transformer模型", "DeepLearning", ("Transformer", "变换器模型")),
        C("RAG", "检索增强生成", "LargeLanguageModel", ("RAG", "知识库问答", "检索增强")),
        C("Agent", "AI智能体", "LargeLanguageModel", ("Agent", "智能体", "AI Agent")),
        C("MultiAgent", "多智能体", "Agent", ("Multi-Agent", "多Agent")),
        C("PromptEngineering", "提示词工程", "LargeLanguageModel", ("Prompt Engineering", "提示工程"), "Skill"),
        C("FineTuning", "模型微调", "MachineLearning", ("Fine-tuning", "微调"), "Skill"),
        C("LoRA", "LoRA微调", "FineTuning", ("LoRA", "低秩微调"), "Skill"),
        C("VectorDatabase", "向量数据库", "Technology", ("Vector DB", "向量库")),
        C("KnowledgeGraph", "知识图谱", "ArtificialIntelligence", ("Knowledge Graph", "KG")),
        C("Ontology", "知识本体", "KnowledgeGraph", ("Ontology", "领域本体")),
        C("Programming", "编程", "Technology", ("programming",), "Skill"),
        C("Python", "Python编程", "Programming", ("Python",), "Skill"),
        C("Java", "Java编程", "Programming", ("Java",), "Skill"),
        C("JavaScript", "JavaScript编程", "Programming", ("JavaScript", "JS"), "Skill"),
        C("WebDevelopment", "Web开发", "Programming", ("网页开发", "前端开发"), "Skill"),
        C("DataScience", "数据科学", "Technology", ("Data Science", "数据分析")),
        C("LangChain", "LangChain", "Agent", (), "Skill"),
        C("LangGraph", "LangGraph", "Agent", (), "Skill"),
        C("ChromaDB", "ChromaDB", "VectorDatabase", ("Chroma",), "Skill"),
        C("Neo4j", "Neo4j", "KnowledgeGraph", (), "Skill"),
        C("PyTorch", "PyTorch", "DeepLearning", ("Torch",), "Skill"),
        C("TensorFlow", "TensorFlow", "DeepLearning", ("TF框架",), "Skill"),
        C("ComputerVision", "计算机视觉", "ArtificialIntelligence", ("Computer Vision", "CV")),
        C("NaturalLanguageProcessing", "自然语言处理", "ArtificialIntelligence", ("NLP",)),
        C("SpeechRecognition", "语音识别", "ArtificialIntelligence", ("ASR",)),
        C("ReinforcementLearning", "强化学习", "MachineLearning", ("RL",)),
        C("DiffusionModel", "扩散模型", "GenerativeAI", ("Diffusion Model",)),
        C("MultimodalAI", "多模态人工智能", "GenerativeAI", ("多模态AI", "Multimodal AI")),
        C("ModelInference", "模型推理", "MachineLearning", ("Inference",), "Skill"),
        C("ModelQuantization", "模型量化", "ModelInference", ("Quantization",), "Skill"),
        C("AIAlignment", "人工智能对齐", "ArtificialIntelligence", ("AI Alignment",)),
        C("FunctionCalling", "函数调用", "Agent", ("Function Calling", "工具调用"), "Skill"),
        C("Embedding", "文本嵌入", "NaturalLanguageProcessing", ("Embedding", "向量嵌入")),
        C("SemanticSearch", "语义搜索", "InformationRetrieval", ("Semantic Search",)),
        C("GraphRAG", "图检索增强生成", "RAG", ("GraphRAG", "Graph RAG")),
        C("ModelContextProtocol", "模型上下文协议", "Agent", ("MCP", "Model Context Protocol")),
        C("OpenAIAPI", "OpenAI API", "LargeLanguageModel", ("OpenAI接口",), "Skill"),
    ],
    "domains/game.ttl": [
        C("ActionGame", "动作游戏", "Game", ("Action Game",)), C("RolePlayingGame", "角色扮演游戏", "Game", ("RPG",)),
        C("StrategyGame", "策略游戏", "Game", ("SLG",)), C("SimulationGame", "模拟游戏", "Game", ("Simulation Game",)),
        C("ShooterGame", "射击游戏", "ActionGame", ("FPS", "TPS")), C("MOBA", "多人在线战术竞技", "Game", ("MOBA",)),
        C("SandboxGame", "沙盒游戏", "Game", ("Sandbox",)), C("IndieGame", "独立游戏", "Game", ("Indie Game",)),
        C("MobileGame", "手机游戏", "Game", ("手游",)), C("ConsoleGame", "主机游戏", "Game", ("Console Game",)),
        C("PCGame", "电脑游戏", "Game", ("PC游戏",)), C("GameGuide", "游戏攻略", "Game", ("攻略",), "Skill"),
        C("Speedrun", "速通", "Game", ("Speedrun",)), C("Esports", "电子竞技", "Game", ("电竞", "Esports")),
        C("GameReview", "游戏评测", "Game", ("Game Review",)), C("GameLore", "游戏剧情解析", "Game", ("世界观解析",)),
        C("Minecraft", "我的世界", "SandboxGame", ("Minecraft", "MC游戏")), C("GenshinImpact", "原神", "RolePlayingGame", ("Genshin Impact",)),
        C("HonkaiStarRail", "崩坏星穹铁道", "RolePlayingGame", ("星穹铁道",)), C("LeagueOfLegends", "英雄联盟", "MOBA", ("LOL游戏",)),
        C("Dota2", "Dota 2", "MOBA", ("DOTA2",)), C("CounterStrike", "反恐精英", "ShooterGame", ("CS2", "CSGO")),
        C("Valorant", "无畏契约", "ShooterGame", ("VALORANT",)), C("Nintendo", "任天堂游戏", "ConsoleGame", ("Nintendo",)),
        C("PlayStation", "PlayStation游戏", "ConsoleGame", ("PS5",)), C("Steam", "Steam游戏", "PCGame", ("Steam平台",)),
        C("BoardGame", "桌面游戏", "Game", ("桌游",)), C("VirtualRealityGame", "虚拟现实游戏", "Game", ("VR游戏",)),
    ],
    "domains/animation.ttl": [
        C("Anime", "日本动画", "Animation", ("Anime", "日漫")), C("ChineseAnimation", "国产动画", "Animation", ("国创", "国漫")),
        C("AnimationFilm", "动画电影", "Animation", ("Animated Film",)), C("ShortAnimation", "动画短片", "Animation", ("Animation Short",)),
        C("MechaAnime", "机甲动画", "Anime", ("机战动画",)), C("IsekaiAnime", "异世界动画", "Anime", ("异世界番剧",)),
        C("SchoolAnime", "校园动画", "Anime", ("校园番",)), C("RomanceAnime", "恋爱动画", "Anime", ("恋爱番",)),
        C("ComedyAnime", "搞笑动画", "Anime", ("搞笑番",)), C("MysteryAnime", "悬疑动画", "Anime", ("推理番",)),
        C("ScienceFictionAnime", "科幻动画", "Anime", ("科幻番",)), C("FantasyAnime", "奇幻动画", "Anime", ("奇幻番",)),
        C("SportsAnime", "运动动画", "Anime", ("运动番",)), C("MusicAnime", "音乐动画", "Anime", ("音乐番",)),
        C("SliceOfLifeAnime", "日常系动画", "Anime", ("日常番",)), C("HealingAnime", "治愈系动画", "Anime", ("治愈番",)),
        C("AnimationProduction", "动画制作", "Animation", ("Animation Production",), "Skill"), C("Storyboarding", "动画分镜", "AnimationProduction", ("Storyboard",), "Skill"),
        C("KeyAnimation", "原画", "AnimationProduction", ("Key Animation",), "Skill"), C("VoiceActing", "配音", "Animation", ("声优", "Voice Acting"), "Skill"),
        C("AnimeReview", "动画评论", "Animation", ("番剧点评",)), C("AnimeAnalysis", "动画解析", "Animation", ("番剧解析",)),
        C("Cosplay", "角色扮演", "Animation", ("Cosplay",)), C("OtakuCulture", "御宅文化", "Animation", ("ACG文化",)),
        C("Manga", "漫画", "Animation", ("Comic",)), C("LightNovel", "轻小说", "Animation", ("Light Novel",)),
    ],
    "domains/music.ttl": [
        C("PopMusic", "流行音乐", "Music", ("Pop",)), C("RockMusic", "摇滚音乐", "Music", ("Rock",)),
        C("ElectronicMusic", "电子音乐", "Music", ("Electronic Music", "EDM")), C("ClassicalMusic", "古典音乐", "Music", ("Classical",)),
        C("FolkMusic", "民谣音乐", "Music", ("Folk",)), C("Jazz", "爵士乐", "Music", ("Jazz",)),
        C("HipHop", "嘻哈音乐", "Music", ("Hip-Hop", "说唱")), C("MetalMusic", "金属音乐", "RockMusic", ("Metal",)),
        C("ChineseTraditionalMusic", "中国传统音乐", "Music", ("国乐",)), C("Vocaloid", "虚拟歌手音乐", "Music", ("VOCALOID",)),
        C("GameMusic", "游戏音乐", "Music", ("Game OST",)), C("AnimeMusic", "动画音乐", "Music", ("Anime OST",)),
        C("FilmScore", "影视配乐", "Music", ("Film Score",)), C("MusicTheory", "乐理", "Music", ("Music Theory",), "Skill"),
        C("Composition", "作曲", "Music", ("Composition",), "Skill"), C("Arrangement", "编曲", "Music", ("Arrangement",), "Skill"),
        C("MusicProduction", "音乐制作", "Music", ("Music Production",), "Skill"), C("Mixing", "混音", "MusicProduction", ("Mixing",), "Skill"),
        C("Mastering", "母带处理", "MusicProduction", ("Mastering",), "Skill"), C("Singing", "声乐演唱", "Music", ("Singing",), "Skill"),
        C("Guitar", "吉他演奏", "Music", ("Guitar",), "Skill"), C("Piano", "钢琴演奏", "Music", ("Piano",), "Skill"),
        C("Drums", "鼓演奏", "Music", ("Drumming",), "Skill"), C("MusicCover", "音乐翻唱", "Music", ("Cover Song",)),
        C("LiveMusic", "音乐现场", "Music", ("Live Music", "现场演出")),
    ],
    "domains/film.ttl": [
        C("ActionFilm", "动作电影", "Film", ("Action Film",)), C("ComedyFilm", "喜剧电影", "Film", ("Comedy Film",)),
        C("DramaFilm", "剧情电影", "Film", ("Drama Film",)), C("ScienceFictionFilm", "科幻电影", "Film", ("Sci-Fi Film",)),
        C("HorrorFilm", "恐怖电影", "Film", ("Horror Film",)), C("ThrillerFilm", "惊悚电影", "Film", ("Thriller",)),
        C("MysteryFilm", "悬疑电影", "Film", ("Mystery Film",)), C("RomanceFilm", "爱情电影", "Film", ("Romance Film",)),
        C("CrimeFilm", "犯罪电影", "Film", ("Crime Film",)), C("WarFilm", "战争电影", "Film", ("War Film",)),
        C("DocumentaryFilm", "纪实电影", "Film", ("Documentary Film",)), C("ArtFilm", "艺术电影", "Film", ("Art Film",)),
        C("ChineseCinema", "华语电影", "Film", ("Chinese Cinema",)), C("WorldCinema", "世界电影", "Film", ("World Cinema",)),
        C("TelevisionDrama", "电视连续剧", "Film", ("TV Series",)), C("WebSeries", "网络剧", "Film", ("Web Series",)),
        C("VarietyShow", "综艺节目", "Film", ("Variety Show",)), C("FilmReview", "影评", "Film", ("Film Review",)),
        C("FilmAnalysis", "影视解析", "Film", ("Film Analysis",)), C("Screenwriting", "编剧", "Film", ("Screenwriting",), "Skill"),
        C("Directing", "导演", "Film", ("Directing",), "Skill"), C("Cinematography", "电影摄影", "Film", ("Cinematography",), "Skill"),
        C("FilmEditing", "影视剪辑", "Film", ("Film Editing",), "Skill"), C("VisualEffects", "视觉特效", "Film", ("VFX",), "Skill"),
        C("SoundDesign", "影视声音设计", "Film", ("Sound Design",), "Skill"),
    ],
    "domains/knowledge.ttl": [
        C("Science", "自然科学", "Knowledge", ("Science",)), C("Mathematics", "数学", "Knowledge", ("Mathematics", "Math")),
        C("Physics", "物理学", "Science", ("Physics",)), C("Chemistry", "化学", "Science", ("Chemistry",)),
        C("Biology", "生物学", "Science", ("Biology",)), C("Astronomy", "天文学", "Science", ("Astronomy",)),
        C("EarthScience", "地球科学", "Science", ("Earth Science",)), C("Medicine", "医学科普", "Knowledge", ("Medical Science",)),
        C("History", "历史", "Knowledge", ("History",)), C("Geography", "地理", "Knowledge", ("Geography",)),
        C("Philosophy", "哲学", "Knowledge", ("Philosophy",)), C("Psychology", "心理学", "Knowledge", ("Psychology",)),
        C("Economics", "经济学", "Knowledge", ("Economics",)), C("Sociology", "社会学", "Knowledge", ("Sociology",)),
        C("Law", "法律知识", "Knowledge", ("Law",)), C("Linguistics", "语言学", "Knowledge", ("Linguistics",)),
        C("Literature", "文学", "Knowledge", ("Literature",)), C("ArtHistory", "艺术史", "Knowledge", ("Art History",)),
        C("Education", "教育", "Knowledge", ("Education",)), C("LearningMethods", "学习方法", "Education", ("Study Skills",), "Skill"),
        C("ExamPreparation", "考试备考", "Education", ("Exam Prep",), "Skill"), C("InformationRetrieval", "信息检索", "Knowledge", ("Information Retrieval", "IR"), "Skill"),
        C("AcademicWriting", "学术写作", "Education", ("Academic Writing",), "Skill"), C("ResearchMethods", "研究方法", "Education", ("Research Methods",), "Skill"),
        C("DataVisualization", "数据可视化", "DataScience", ("Data Visualization",), "Skill"), C("Statistics", "统计学", "Mathematics", ("Statistics",)),
        C("PopularScience", "科普创作", "Knowledge", ("Science Communication",), "Skill"), C("Museum", "博物馆知识", "Knowledge", ("Museum",)),
    ],
    "domains/life.ttl": [
        C("Cooking", "烹饪", "Food", ("Cooking",), "Skill"), C("Baking", "烘焙", "Food", ("Baking",), "Skill"),
        C("Coffee", "咖啡", "Food", ("Coffee",)), C("Tea", "茶文化", "Food", ("Tea",)),
        C("Travel", "旅行", "Life", ("Travel",)), C("CityWalk", "城市漫步", "Travel", ("City Walk",)),
        C("Photography", "摄影", "Life", ("Photography",), "Skill"), C("Videography", "视频拍摄", "Life", ("Videography",), "Skill"),
        C("HomeImprovement", "家居改造", "Life", ("Home Improvement",), "Skill"), C("InteriorDesign", "室内设计", "Life", ("Interior Design",), "Skill"),
        C("Gardening", "园艺", "Life", ("Gardening",), "Skill"), C("Handicraft", "手工", "Life", ("DIY手作",), "Skill"),
        C("Fitness", "健身", "Sports", ("Fitness",)), C("Running", "跑步", "Sports", ("Running",)),
        C("Cycling", "骑行", "Sports", ("Cycling",)), C("Basketball", "篮球", "Sports", ("Basketball",)),
        C("Football", "足球", "Sports", ("Football", "Soccer")), C("Swimming", "游泳", "Sports", ("Swimming",)),
        C("Yoga", "瑜伽", "Sports", ("Yoga",)), C("Outdoor", "户外运动", "Sports", ("Outdoor",)),
        C("PetCare", "宠物养护", "Animals", ("Pet Care",), "Skill"), C("Cat", "猫", "Animals", ("Cat",)),
        C("Dog", "狗", "Animals", ("Dog",)), C("FashionStyling", "穿搭", "Fashion", ("Styling",), "Skill"),
        C("Skincare", "护肤", "Fashion", ("Skincare",)), C("Makeup", "美妆", "Fashion", ("Makeup",)),
        C("PersonalFinance", "个人理财", "Life", ("Personal Finance",)), C("CareerDevelopment", "职业发展", "Life", ("Career Development",)),
    ],
}


PREFIXES = """@prefix bili: <https://bilibili.local/ontology/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix dcterms: <http://purl.org/dc/terms/> .

"""


def literal(value: str, language: str | None = None) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"' + (f"@{language}" if language else "")


def concept_ttl(row, source: str) -> str:
    identifier, label, parent, aliases, kind = row
    properties = [
        f"a bili:{kind}, skos:Concept",
        f"skos:prefLabel {literal(label, 'zh')}",
        f"skos:definition {literal(f'在B站内容理解与兴趣画像中表示“{label}”的受控概念。', 'zh')}",
        f"dcterms:source {literal(source)}",
        'bili:status "active"',
        f'bili:maintenanceVersion "{VERSION}"',
    ]
    if aliases:
        properties.append("skos:altLabel " + ", ".join(
            literal(alias, "en" if alias.isascii() else "zh") for alias in aliases
        ))
    if parent:
        properties.append(f"skos:broader bili:{parent}")
    return f"bili:{identifier} " + " ;\n    ".join(properties) + " .\n"


def write_core() -> None:
    header = PREFIXES + f"""bili:ontology-v2 a owl:Ontology ;
    rdfs:label "B站内容与兴趣本体 V2"@zh ;
    owl:versionInfo "{VERSION}" .

bili:Video a owl:Class .
bili:Creator a owl:Class .
bili:User a owl:Class .
bili:FavoriteFolder a owl:Class .
bili:RecommendationEvent a owl:Class .
bili:Topic a owl:Class ; rdfs:subClassOf skos:Concept .
bili:Skill a owl:Class ; rdfs:subClassOf skos:Concept .
bili:ContentFormat a owl:Class ; rdfs:subClassOf skos:Concept .
bili:Difficulty a owl:Class ; rdfs:subClassOf skos:Concept .
bili:Category a owl:Class ; rdfs:subClassOf skos:Concept .
bili:PersonalConcept a owl:Class ; rdfs:subClassOf skos:Concept .

bili:aboutTopic a owl:ObjectProperty ; rdfs:domain bili:Video ; rdfs:range skos:Concept .
bili:teaches a owl:ObjectProperty ; rdfs:domain bili:Video ; rdfs:range bili:Skill .
bili:requires a owl:ObjectProperty ; rdfs:domain skos:Concept ; rdfs:range skos:Concept .
bili:hasFormat a owl:ObjectProperty ; rdfs:domain bili:Video ; rdfs:range bili:ContentFormat .
bili:hasDifficulty a owl:ObjectProperty ; rdfs:domain bili:Video ; rdfs:range bili:Difficulty .
bili:createdBy a owl:ObjectProperty ; rdfs:domain bili:Video ; rdfs:range bili:Creator .
bili:interestEvidenceFor a owl:ObjectProperty ; rdfs:domain bili:RecommendationEvent ; rdfs:range skos:Concept .
bili:status a owl:DatatypeProperty ; rdfs:domain skos:Concept ; rdfs:range xsd:string .
bili:maintenanceVersion a owl:DatatypeProperty ; rdfs:domain skos:Concept ; rdfs:range xsd:string .
bili:bilibiliTid a owl:DatatypeProperty ; rdfs:domain bili:Category ; rdfs:range xsd:integer .

"""
    body = "\n".join(concept_ttl(row, "Ontology V2 editorial core") for row in CORE)
    deprecated = """
bili:AIGeneratedContentLegacy a bili:Topic, skos:Concept ;
    skos:prefLabel "AI生成内容（旧称）"@zh ;
    skos:definition "生成式人工智能内容的历史术语，仅用于兼容旧标注。"@zh ;
    dcterms:source "Ontology V1 compatibility review" ;
    bili:status "deprecated" ; bili:maintenanceVersion "2.0.0" ;
    owl:deprecated true ; dcterms:isReplacedBy bili:GenerativeAI .
"""
    (ONTOLOGY / "core.ttl").write_text(header + body + deprecated, encoding="utf-8")


def write_taxonomy() -> None:
    rows = []
    for identifier, label, tid, aliases in TAXONOMY:
        ttl = concept_ttl(C(identifier, label, None, aliases, "Category"), "Bilibili public partition taxonomy and editorial mapping")
        ttl = ttl[:-2] + f' ;\n    bili:bilibiliTid {tid} .\n'
        rows.append(ttl)
    (ONTOLOGY / "bilibili-taxonomy.ttl").write_text(PREFIXES + "\n".join(rows), encoding="utf-8")


def main() -> None:
    (ONTOLOGY / "domains").mkdir(parents=True, exist_ok=True)
    write_core()
    write_taxonomy()
    for relative, rows in MODULES.items():
        path = ONTOLOGY / relative
        source = f"Ontology V2 editorial curation: {path.stem} domain"
        path.write_text(PREFIXES + "\n".join(concept_ttl(row, source) for row in rows), encoding="utf-8")
    modules = ["core.ttl", "bilibili-taxonomy.ttl", *MODULES.keys()]
    manifest = {
        "schema_version": "2.0",
        "ontology_version": "bili-ontology-2.0.0",
        "modules": modules,
        "personal_namespace_policy": "Personal concepts are stored per user and are never loaded into the public manifest.",
    }
    (ONTOLOGY / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    count = len(CORE) + 1 + len(TAXONOMY) + sum(len(rows) for rows in MODULES.values())
    print(json.dumps({"modules": len(modules), "concepts": count}, ensure_ascii=False))


if __name__ == "__main__":
    main()
