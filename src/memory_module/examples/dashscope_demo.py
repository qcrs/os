from __future__ import annotations

import os
from pathlib import Path

from memory_module.embedders import BM25Encoder, DashScopeEmbedder
from memory_module.module import MemoryModule


def find_bm25_snapshot() -> Path:
    hub = Path.home() / ".cache/huggingface/hub/models--Qdrant--bm25/snapshots"
    snapshots = sorted(path for path in hub.glob("*") if path.is_dir())
    if not snapshots:
        raise RuntimeError(f"BM25 snapshot not found under {hub}")
    return snapshots[-1]


def main() -> None:
    if not os.getenv("DASHSCOPE_API_KEY"):
        raise RuntimeError("Please set DASHSCOPE_API_KEY before running this example")

    dense_embedder = DashScopeEmbedder(
        model="text-embedding-v4",
        dimension=1024,
    )
    bm25_encoder = BM25Encoder(model_path=find_bm25_snapshot())
    memory = MemoryModule(
        dense_embedder=dense_embedder,
        bm25_encoder=bm25_encoder,
        qdrant_path="memory_module/data/qdrant_dashscope",
        collection_name="shared_memories_v4_1024_topic_v1",
    )

    """
    批量生成 100+ 条测试记忆
    按 7 个推荐系统任务的子主题系统化扩展。
    直接运行即可获得 MEMORIES 列表。
    """

    MEMORIES: list[dict] = []

    def _add(task_id, topic, agent, mtype, content, keywords):
        MEMORIES.append({
            "content": content,
            "keywords": keywords,
            "memory_type": mtype,
            "source_agent": agent,
            "source_task_id": task_id,
            "task_topic": topic,
        })

    # ═══════════════════════════════════════════════════
    #  T1: 需求分析与用户画像 (15 条)
    # ═══════════════════════════════════════════════════
    T1 = "task_1"
    TP1 = "需求分析与用户画像"

    _add(T1, TP1, "retriever", "evidence",
        "电商平台日活500万，月活2200万，SKU 200万，日均订单量180万单。",
        ["DAU", "MAU", "SKU", "订单量"])

    _add(T1, TP1, "retriever", "evidence",
        "用户行为包含浏览、点击、加购、购买、收藏、分享六种事件，其中浏览和点击占比超过85%。",
        ["用户行为", "浏览", "点击", "加购", "购买"])

    _add(T1, TP1, "retriever", "evidence",
        "平均每用户日产生45条行为记录，高活跃用户（Top 10%）日均产生200+条，长尾用户日均不足5条。",
        ["行为频次", "活跃用户", "长尾用户"])

    _add(T1, TP1, "summarizer", "conclusion",
        "推荐系统需覆盖三个场景：首页信息流（曝光CTR目标8%）、商品详情页（关联推荐CVR目标3%）、购物车页（凑单推荐客单价提升15%）。",
        ["推荐场景", "首页", "详情页", "购物车", "CTR", "CVR"])

    _add(T1, TP1, "summarizer", "design",
        "用户画像模型分三层：静态属性（性别、年龄段、城市等级）、短期兴趣（7天点击类目分布）、长期偏好（90天购买类目TF-IDF向量）。",
        ["用户画像", "静态属性", "短期兴趣", "长期偏好", "TF-IDF"])

    _add(T1, TP1, "summarizer", "conclusion",
        "核心业务指标：CTR=点击/曝光，CVR=购买/点击，GMV=订单金额总和，人均推荐GMV=推荐用户平均贡献GMV。",
        ["CTR", "CVR", "GMV", "业务指标"])

    _add(T1, TP1, "executor", "evidence",
        "用户分群分析显示：价格敏感型占42%、品牌忠诚型占23%、品质导向型占18%、尝鲜猎奇型占17%。",
        ["用户分群", "价格敏感", "品牌忠诚", "品质导向"])

    _add(T1, TP1, "planner", "strategy",
        "推荐系统分两期建设：一期实现基础召回+排序（3个月），二期加入实时特征和深度模型（2个月）。",
        ["项目规划", "分期建设", "里程碑"])

    _add(T1, TP1, "retriever", "evidence",
        "竞品分析：淘宝推荐系统CTR约12%，京东约10%，拼多多约9%，行业平均水平约8%。",
        ["竞品分析", "淘宝", "京东", "拼多多", "CTR"])

    _add(T1, TP1, "summarizer", "conclusion",
        "推荐系统ROI预估：首页CTR提升2%可带来日均GMV增长约150万元，年化收益约5.5亿元。",
        ["ROI", "收益预估", "GMV增长"])

    _add(T1, TP1, "executor", "evidence",
        "现有推荐系统基线测试：基于热门排序的CTR为4.2%，基于协同过滤的CTR为5.8%。",
        ["基线测试", "热门排序", "协同过滤", "CTR"])

    _add(T1, TP1, "retriever", "evidence",
        "用户留存分析：7日留存率62%、30日留存率38%，推荐触达用户的留存率比未触达高15个百分点。",
        ["留存率", "7日留存", "30日留存"])

    _add(T1, TP1, "summarizer", "design",
        "用户行为实时流处理需求：端到端延迟<500ms，峰值QPS 10万，需支持事件去重和乱序处理。",
        ["实时处理", "延迟", "QPS", "去重"])

    _add(T1, TP1, "planner", "strategy",
        "数据合规要求：用户行为数据保留期限不超过180天，需支持GDPR要求的数据删除请求。",
        ["数据合规", "GDPR", "数据保留", "隐私"])

    _add(T1, TP1, "summarizer", "conclusion",
        "性别推断准确率92%，年龄段推断准确率78%，城市等级推断准确率95%，可作为冷启动用户画像补充。",
        ["画像推断", "准确率", "冷启动"])


    # ═══════════════════════════════════════════════════
    #  T2: 推荐算法技术选型 (15 条)
    # ═══════════════════════════════════════════════════
    T2 = "task_2"
    TP2 = "推荐算法技术选型"

    _add(T2, TP2, "retriever", "evidence",
        "协同过滤（UserCF/ItemCF）实现简单可解释，但冷启动严重，200万SKU相似度矩阵计算开销极大。",
        ["协同过滤", "UserCF", "ItemCF", "冷启动"])

    _add(T2, TP2, "retriever", "evidence",
        "矩阵分解ALS在Spark上可分布式训练，处理200万SKU需要约32GB内存，训练时间约4小时。",
        ["ALS", "矩阵分解", "Spark", "分布式"])

    _add(T2, TP2, "retriever", "evidence",
        "DSSM双塔模型适合召回层，将200万候选缩小到500，推理延迟<20ms，支持ANN在线检索。",
        ["DSSM", "双塔", "召回", "ANN"])

    _add(T2, TP2, "retriever", "evidence",
        "DIN注意力模型在排序层表现优异，通过attention机制关注与候选最相关的历史行为，AUC提升约2%。",
        ["DIN", "attention", "排序", "AUC"])

    _add(T2, TP2, "retriever", "evidence",
        "DeepFM模型同时学习低阶和高阶特征交叉，适合特征丰富的排序场景，但训练成本比LR高5倍。",
        ["DeepFM", "特征交叉", "排序", "训练成本"])

    _add(T2, TP2, "retriever", "evidence",
        "Word2Vec/Item2Vec可以学习物品的分布式表示，训练速度快，适合生成物品embedding用于内容推荐。",
        ["Word2Vec", "Item2Vec", "embedding", "内容推荐"])

    _add(T2, TP2, "summarizer", "conclusion",
        "选型结论：召回层DSSM双塔，排序层DIN注意力网络，冷启动降级为Item2Vec+类目相似度的内容推荐。",
        ["DSSM", "DIN", "Item2Vec", "选型", "冷启动"])

    _add(T2, TP2, "planner", "strategy",
        "协同过滤保留作为A/B测试对照组基线，同时用于评估深度学习模型的增量提升。",
        ["协同过滤", "AB测试", "基线", "对照组"])

    _add(T2, TP2, "executor", "evidence",
        "DSSM离线训练：128维embedding，batch_size=4096，学习率1e-3，10个epoch约2小时（单卡V100）。",
        ["DSSM", "训练参数", "embedding", "V100"])

    _add(T2, TP2, "executor", "evidence",
        "DIN离线训练：最大历史行为长度50，attention维度64，10个epoch约3小时（单卡V100），AUC=0.7842。",
        ["DIN", "训练参数", "AUC", "attention"])

    _add(T2, TP2, "summarizer", "design",
        "多路召回策略：DSSM向量召回（300条）+ 热门物品（100条）+ 近期点击物品相似物品（100条），合并去重后500条进入粗排。",
        ["多路召回", "DSSM", "热门", "相似物品"])

    _add(T2, TP2, "retriever", "evidence",
        "图神经网络（GraphSAGE/PinSage）可利用用户-物品交互图，但工程复杂度高，暂不纳入一期方案。",
        ["图神经网络", "GraphSAGE", "PinSage", "交互图"])

    _add(T2, TP2, "summarizer", "conclusion",
        "冷启动方案：新用户使用Item2Vec+类目相似度做内容推荐，新商品通过属性embedding匹配相似商品的协同信号，7天后切换个性化模型。",
        ["冷启动", "新用户", "新商品", "Item2Vec", "内容推荐"])

    _add(T2, TP2, "planner", "strategy",
        "模型迭代计划：每季度评估一次算法架构，逐步引入多目标优化（MMOE）和序列推荐（SASRec）。",
        ["模型迭代", "MMOE", "SASRec", "多目标"])

    _add(T2, TP2, "summarizer", "evidence",
        "算法对比评估表：协同过滤AUC=0.72，DSSM+DIN AUC=0.784，DeepFM AUC=0.778，选择DSSM+DIN组合。",
        ["AUC对比", "协同过滤", "DSSM", "DIN", "DeepFM"])


    # ═══════════════════════════════════════════════════
    #  T3: 数据采集与存储方案 (15 条)
    # ═══════════════════════════════════════════════════
    T3 = "task_3"
    TP3 = "数据采集与存储方案"

    _add(T3, TP3, "executor", "design",
        "埋点规范：每条事件必填user_id, item_id, event_type, timestamp, page_source, device_type，扩展字段用JSON properties。",
        ["埋点", "事件", "数据采集"])

    _add(T3, TP3, "summarizer", "design",
        "Redis Cluster存储实时特征：用户特征hash结构TTL 24h，物品统计sorted set每小时更新，6主6从读写分离。",
        ["Redis", "Cluster", "实时特征", "读写分离"])

    _add(T3, TP3, "executor", "design",
        "ETL流程：Kafka消费行为日志→Flink实时清洗→写入Hive按天分区→Spark特征工程→输出TFRecord训练样本。",
        ["ETL", "Kafka", "Flink", "Hive", "Spark", "TFRecord"])

    _add(T3, TP3, "summarizer", "conclusion",
        "特征工程输出三组：用户特征128维、物品特征64维、交叉特征32维，总计224维。",
        ["特征工程", "用户特征", "物品特征", "交叉特征"])

    _add(T3, TP3, "executor", "evidence",
        "Kafka集群配置：3个broker，topic按event_type分区，单分区写入峰值5万msg/s，消费端LAG控制在1000以内。",
        ["Kafka", "broker", "分区", "吞吐量"])

    _add(T3, TP3, "executor", "evidence",
        "Flink实时清洗规则：过滤机器人流量（UA黑名单）、去重（10分钟窗口内相同user_id+item_id+event_type）、补全缺失字段。",
        ["Flink", "数据清洗", "去重", "机器人过滤"])

    _add(T3, TP3, "summarizer", "design",
        "Hive表结构：按天分区（dt=yyyy-MM-dd），每天约2亿条记录，单日数据量约15GB（Parquet格式）。",
        ["Hive", "分区", "Parquet", "数据量"])

    _add(T3, TP3, "retriever", "evidence",
        "HBase vs Redis特征存储对比：HBase适合大规模离线特征（TB级），Redis适合小规模低延迟实时特征（GB级）。",
        ["HBase", "Redis", "特征存储", "对比"])

    _add(T3, TP3, "summarizer", "design",
        "用户实时特征列表：最近1小时点击类目分布、最近24小时浏览商品数、当前session点击序列、最近加购但未购买的商品列表。",
        ["实时特征", "点击类目", "session", "加购"])

    _add(T3, TP3, "summarizer", "design",
        "物品实时统计特征：近1小时点击数、近24小时销量、实时库存状态、价格波动率。",
        ["物品特征", "实时统计", "点击数", "销量"])

    _add(T3, TP3, "executor", "evidence",
        "特征一致性验证：离线特征与在线特征的一致率需达到99.5%以上，通过shadow mode双写对比。",
        ["特征一致性", "shadow mode", "验证"])

    _add(T3, TP3, "planner", "strategy",
        "数据质量监控：每小时检查埋点覆盖率（>98%）、字段完整率（>99%）、数据延迟（<5分钟）。",
        ["数据质量", "覆盖率", "完整率", "延迟"])

    _add(T3, TP3, "summarizer", "design",
        "离线样本构造：正样本=购买事件，负样本=曝光未点击随机采样（正负比1:4），样本按时间排序防止穿越。",
        ["样本构造", "正样本", "负样本", "时间穿越"])

    _add(T3, TP3, "executor", "evidence",
        "Spark特征工程性能：224维特征提取，100亿样本约需3小时（50个executor，每个4C16G）。",
        ["Spark", "特征工程", "性能", "executor"])

    _add(T3, TP3, "summarizer", "conclusion",
        "数据存储成本估算：Redis Cluster月成本约1.2万（6节点16G），Hive存储月成本约3000（按量付费），Kafka月成本约5000。",
        ["存储成本", "Redis", "Hive", "Kafka", "预算"])


    # ═══════════════════════════════════════════════════
    #  T4: 推荐模型设计与训练方案 (15 条)
    # ═══════════════════════════════════════════════════
    T4 = "task_4"
    TP4 = "推荐模型设计与训练方案"

    _add(T4, TP4, "summarizer", "design",
        "DSSM用户塔：128维用户特征→Dense(256)→ReLU→Dense(128)→ReLU→Dense(64)→L2归一化，输出64维embedding。",
        ["DSSM", "用户塔", "embedding", "网络架构"])

    _add(T4, TP4, "summarizer", "design",
        "DSSM物品塔：64维物品特征→Dense(128)→ReLU→Dense(64)→L2归一化，输出64维embedding，使用sampled softmax loss。",
        ["DSSM", "物品塔", "softmax loss", "网络架构"])

    _add(T4, TP4, "retriever", "evidence",
        "DIN排序模型通过attention机制关注候选物品与用户历史行为中最相关的交互，AUC提升约2%。",
        ["DIN", "attention", "AUC", "排序"])

    _add(T4, TP4, "planner", "strategy",
        "训练策略：离线全量每周一次（30天数据），增量每日一次（1天fine-tune），自动触发AUC/NDCG评估。",
        ["训练策略", "离线", "增量", "AUC", "NDCG"])

    _add(T4, TP4, "executor", "evidence",
        "Faiss索引构建：200万物品64维embedding，使用IVF4096_HNSW32索引，构建时间12分钟，查询P99<5ms。",
        ["Faiss", "ANN", "索引", "HNSW", "IVF"])

    _add(T4, TP4, "executor", "evidence",
        "模型大小对比：DSSM双塔共15MB，DIN排序模型45MB，全部可加载到单GPU显存。",
        ["模型大小", "DSSM", "DIN", "GPU"])

    _add(T4, TP4, "summarizer", "design",
        "DIN网络结构：用户行为序列(最长50)→Attention Pooling(key=候选物品embedding)→concat用户特征→MLP(256→128→1)。",
        ["DIN", "网络结构", "Attention Pooling", "MLP"])

    _add(T4, TP4, "summarizer", "design",
        "负采样策略：DSSM使用in-batch negatives(batch_size=4096自动产生负样本)，DIN使用曝光未点击作为负样本。",
        ["负采样", "in-batch", "曝光未点击"])

    _add(T4, TP4, "executor", "evidence",
        "离线评估结果：DSSM召回率Recall@500=85.3%，DIN排序AUC=0.7842，NDCG@20=0.4156。",
        ["离线评估", "Recall", "AUC", "NDCG"])

    _add(T4, TP4, "retriever", "evidence",
        "序列推荐模型SASRec使用self-attention建模行为序列，效果略优于DIN但推理延迟高3倍，暂列为二期候选。",
        ["SASRec", "self-attention", "序列推荐"])

    _add(T4, TP4, "summarizer", "design",
        "embedding更新策略：物品embedding每日增量更新，Faiss索引每日凌晨重建，新品实时插入临时索引。",
        ["embedding更新", "Faiss", "增量更新", "新品"])

    _add(T4, TP4, "planner", "strategy",
        "模型质量红线：AUC下降超过0.5%自动回滚，NDCG下降超过1%触发告警人工确认。",
        ["质量红线", "回滚", "告警", "AUC"])

    _add(T4, TP4, "executor", "evidence",
        "GPU训练资源：DSSM单卡V100训练2小时，DIN单卡V100训练3小时，总训练周期含数据准备约8小时。",
        ["GPU", "V100", "训练时间", "资源"])

    _add(T4, TP4, "summarizer", "conclusion",
        "粗排模型采用轻量LR+特征交叉，对500候选精简到100，延迟<5ms，AUC=0.74，牺牲精度换取速度。",
        ["粗排", "LR", "延迟", "AUC"])

    _add(T4, TP4, "summarizer", "design",
        "特征输入拼接方式：[用户静态特征(32维)] + [用户实时特征(96维)] + [物品特征(64维)] + [交叉特征(32维)] = 224维。",
        ["特征拼接", "输入维度", "用户特征", "物品特征"])


    # ═══════════════════════════════════════════════════
    #  T5: 推荐服务API设计 (12 条)
    # ═══════════════════════════════════════════════════
    T5 = "task_5"
    TP5 = "推荐服务API设计"

    _add(T5, TP5, "summarizer", "design",
        "四级架构：召回(DSSM 200万→500 <20ms)→粗排(LR 500→100 <5ms)→精排(DIN 100→50 <30ms)→重排(规则 50→20 <10ms)，P99<100ms。",
        ["推荐架构", "召回", "粗排", "精排", "重排", "延迟"])

    _add(T5, TP5, "executor", "design",
        "API接口：POST /api/v1/recommend，入参{user_id, scene, context, size}，出参{items: [{item_id, score, reason}], request_id, latency_ms}。",
        ["API", "接口定义", "请求格式", "响应格式"])

    _add(T5, TP5, "summarizer", "strategy",
        "降级策略三级：L1模型超时→热门缓存，L2特征不可用→规则推荐，L3全链路故障→运营兜底列表。",
        ["降级策略", "热门推荐", "规则推荐", "兜底"])

    _add(T5, TP5, "summarizer", "design",
        "三个场景差异化配置：首页feed推20条，详情页关联推10条，购物车凑单推5条，各场景独立的重排规则。",
        ["场景配置", "首页", "详情页", "购物车"])

    _add(T5, TP5, "executor", "design",
        "缓存策略：用户最近推荐结果Redis缓存5分钟（防刷新重复），物品embedding本地LRU缓存（命中率>95%）。",
        ["缓存", "Redis", "LRU", "命中率"])

    _add(T5, TP5, "summarizer", "design",
        "重排规则：同类目物品不超过30%、已购物品过滤、价格区间打散、新品boost权重1.2倍。",
        ["重排规则", "多样性", "去重", "新品boost"])

    _add(T5, TP5, "executor", "evidence",
        "压测结果：单实例QPS 800，3副本总QPS 2400，P99延迟82ms，满足峰值1500 QPS需求。",
        ["压测", "QPS", "延迟", "性能"])

    _add(T5, TP5, "summarizer", "design",
        "请求链路：Nginx→API Gateway(限流+鉴权)→推荐服务→特征服务(Redis)+模型服务(TorchServe)。",
        ["请求链路", "Nginx", "Gateway", "限流"])

    _add(T5, TP5, "retriever", "evidence",
        "推荐理由生成：基于用户最近行为匹配推荐原因模板，如'根据您浏览的[类目]推荐'、'买了[商品]的人也买了'。",
        ["推荐理由", "解释性", "模板"])

    _add(T5, TP5, "planner", "strategy",
        "API版本管理：使用URL路径版本号/v1/，新版本并行运行至少2周，旧版本至少保留30天。",
        ["版本管理", "API", "兼容性"])

    _add(T5, TP5, "summarizer", "conclusion",
        "推荐服务SLA：可用性99.95%，P99延迟<100ms，降级响应时间<10ms。",
        ["SLA", "可用性", "延迟", "降级"])

    _add(T5, TP5, "executor", "evidence",
        "推荐去重策略：session级去重（同次session不重复推荐）+ 24小时全局去重（避免频繁推荐相同物品）。",
        ["去重", "session", "全局去重"])


    # ═══════════════════════════════════════════════════
    #  T6: A/B测试与效果评估 (12 条)
    # ═══════════════════════════════════════════════════
    T6 = "task_6"
    TP6 = "AB测试与效果评估"

    _add(T6, TP6, "summarizer", "design",
        "分桶策略：按user_id哈希分1000桶，实验组和对照组各分配固定桶段，确保用户粒度一致性，每组最少10万用户。",
        ["AB测试", "分桶", "实验组", "对照组"])

    _add(T6, TP6, "summarizer", "conclusion",
        "评估指标体系：主指标(CTR/CVR/人均GMV)、辅助指标(多样性Shannon熵/覆盖率/新颖性=物品平均流行度倒数)。",
        ["评估指标", "CTR", "CVR", "多样性", "覆盖率"])

    _add(T6, TP6, "planner", "strategy",
        "灰度发布：1%内测3天→5%验证3天→20%扩量7天→50%观察7天→100%全量，每阶段需p<0.05。",
        ["灰度发布", "流量", "p-value", "统计显著"])

    _add(T6, TP6, "executor", "evidence",
        "最小检测效应MDE计算：在10万用户样本量下，CTR的MDE约0.3%（alpha=0.05, power=0.8）。",
        ["MDE", "样本量", "统计功效", "alpha"])

    _add(T6, TP6, "summarizer", "design",
        "指标看板设计：实时更新CTR/CVR趋势，每小时计算显著性p值，自动标注指标异常波动。",
        ["看板", "实时", "显著性", "异常检测"])

    _add(T6, TP6, "retriever", "evidence",
        "多目标评估：CTR和CVR可能冲突（标题党提高CTR但降低CVR），需综合评估联合指标=0.4*CTR+0.6*CVR。",
        ["多目标", "CTR", "CVR", "联合指标"])

    _add(T6, TP6, "planner", "strategy",
        "实验排期规则：同一用户同时最多参与2个实验，大促期间冻结实验，实验周期至少覆盖一个完整周末。",
        ["实验排期", "大促", "并行实验"])

    _add(T6, TP6, "executor", "evidence",
        "长期效果追踪：推荐系统上线后需持续30天观察用户留存和复购率，防止短期CTR提升但长期伤害用户体验。",
        ["长期效果", "留存", "复购率", "用户体验"])

    _add(T6, TP6, "summarizer", "design",
        "归因分析：使用last-click归因模型，推荐触达后30分钟内的购买归因于推荐，超过30分钟归因于自然转化。",
        ["归因分析", "last-click", "转化窗口"])

    _add(T6, TP6, "retriever", "evidence",
        "行业经验：推荐系统AB测试中，算法优化带来的CTR提升通常在0.5%-3%之间，超过5%需检查是否存在数据泄漏。",
        ["行业经验", "CTR提升", "数据泄漏"])

    _add(T6, TP6, "summarizer", "conclusion",
        "上线标准：主指标统计显著提升(p<0.05)，辅助指标无显著负向变化，工程指标(延迟/错误率)无回退。",
        ["上线标准", "显著性", "辅助指标", "工程指标"])

    _add(T6, TP6, "executor", "evidence",
        "AA测试验证：在启动AB测试前先跑3天AA测试（两组用相同策略），确认分桶无偏，指标差异<0.1%。",
        ["AA测试", "分桶验证", "无偏"])


    # ═══════════════════════════════════════════════════
    #  T7: 部署上线与监控方案 (15 条)
    # ═══════════════════════════════════════════════════
    T7 = "task_7"
    TP7 = "部署上线与监控方案"

    _add(T7, TP7, "executor", "design",
        "K8s部署：推荐服务Deployment 3副本4C8G HPA按CPU 70%扩缩，特征服务StatefulSet Redis 6节点，模型服务GPU节点TorchServe。",
        ["K8s", "Deployment", "StatefulSet", "HPA", "TorchServe"])

    _add(T7, TP7, "summarizer", "strategy",
        "模型热更新：新模型推送至模型仓库→Sidecar检测→加载shadow副本→离线评估→灰度切换→全量。回滚<30秒。",
        ["热更新", "Sidecar", "灰度切换", "回滚"])

    _add(T7, TP7, "summarizer", "design",
        "监控告警：Prometheus采集QPS/P99/特征缺失率/推荐多样性/CTR波动，Grafana看板，P99>200ms或CTR日跌>10%触发告警。",
        ["Prometheus", "Grafana", "监控", "告警", "P99"])

    _add(T7, TP7, "summarizer", "design",
        "日志采集：ELK Stack收集推荐请求日志（request_id+user_id+推荐结果+延迟），用于离线分析和问题排查。",
        ["ELK", "日志", "request_id", "排查"])

    _add(T7, TP7, "planner", "strategy",
        "容灾方案：推荐服务跨可用区部署，数据库主从跨机房同步，全链路故障时自动切换到运营配置的静态推荐列表。",
        ["容灾", "跨可用区", "主从同步", "静态推荐"])

    _add(T7, TP7, "executor", "design",
        "资源规划：推荐服务3*4C8G=12C24G，Redis 6*16G=96G，模型服务2*T4 GPU，月成本约2.5万元。",
        ["资源规划", "成本", "GPU", "Redis"])

    _add(T7, TP7, "summarizer", "design",
        "健康检查：推荐服务/health接口（检查Redis连接+模型加载状态），K8s liveness/readiness probe配置。",
        ["健康检查", "liveness", "readiness", "probe"])

    _add(T7, TP7, "executor", "evidence",
        "压测环境验证：3副本配置下，持续30分钟2000QPS压测，CPU平均65%，P99稳定在85ms，无OOM。",
        ["压测", "QPS", "CPU", "P99", "OOM"])

    _add(T7, TP7, "summarizer", "strategy",
        "发布流程：开发环境→测试环境（自动化回归）→预发布环境（1%流量）→生产环境（灰度→全量）。",
        ["发布流程", "环境", "回归测试", "灰度"])

    _add(T7, TP7, "retriever", "evidence",
        "Helm Chart版本管理：每次部署生成唯一revision，支持一键回滚到任意历史版本，保留最近10个版本。",
        ["Helm", "版本管理", "回滚", "revision"])

    _add(T7, TP7, "summarizer", "design",
        "告警分级：P0(服务不可用)→5分钟内响应，P1(性能劣化)→30分钟内响应，P2(非核心异常)→下一工作日处理。",
        ["告警分级", "P0", "P1", "响应时间"])

    _add(T7, TP7, "executor", "design",
        "自动扩缩容配置：CPU>70%触发扩容(最大10副本)，CPU<30%持续10分钟触发缩容(最小2副本)。",
        ["自动扩缩容", "HPA", "CPU阈值", "副本数"])

    _add(T7, TP7, "summarizer", "conclusion",
        "SLA承诺：服务可用性99.95%（月停机<22分钟），P99<100ms，降级响应<10ms，模型更新零停机。",
        ["SLA", "可用性", "停机", "零停机"])

    _add(T7, TP7, "planner", "strategy",
        "值班机制：7×24小时oncall轮岗，告警自动推送到企业微信群+电话通知oncall人员。",
        ["值班", "oncall", "企业微信", "告警通知"])

    _add(T7, TP7, "executor", "evidence",
        "混沌工程测试：随机kill一个推荐服务Pod，验证流量自动切换到健康Pod，恢复时间<5秒。",
        ["混沌工程", "Pod", "故障恢复", "自动切换"])


    # ═══════════════════════════════════════════════════
    #  统计
    # ═══════════════════════════════════════════════════
    print(f"总记忆数: {len(MEMORIES)}")
    by_task = {}
    for m in MEMORIES:
        tid = m["source_task_id"]
        by_task[tid] = by_task.get(tid, 0) + 1
    for tid in sorted(by_task):
        print(f"  {tid}: {by_task[tid]} 条")

    try:
        output_path = Path("memory_module/data/dashscope_demo_output.txt")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_lines = []

        queries = [

            # ── 第一组：语义查询（不含精确关键词，纯靠语义理解）──

            "推荐系统应该用什么算法做召回和排序",
            # 期望命中: DSSM双塔(T2), DIN排序(T4), 选型结论(T2)

            "电商平台的用户有哪些行为数据可以用来做个性化推荐",
            # 期望命中: 用户行为(T1), 埋点方案(T3), 用户画像(T1)

            "推荐服务出现故障时如何保证用户体验不中断",
            # 期望命中: 降级策略(T5), 监控告警(T7), 容灾方案

            "如何判断新的推荐算法比老算法效果更好",
            # 期望命中: AB测试(T6), 业务指标(T1), 评估指标(T6)

            "新用户没有历史行为数据怎么做推荐",
            # 期望命中: 冷启动 Item2Vec(T2), 协同过滤冷启动问题(T2)

            # ── 第二组：关键词查询（精确术语，测试 BM25 分词效果）──

            "DSSM双塔模型召回",
            # 期望命中: DSSM相关(T2, T4)

            "Redis Cluster 实时特征",
            # 期望命中: Redis特征存储(T3)

            "Kafka Flink ETL Hive",
            # 期望命中: ETL流程(T3)

            "K8s Deployment HPA TorchServe",
            # 期望命中: K8s部署(T7)

            "Prometheus Grafana 监控告警",
            # 期望命中: 监控方案(T7)

            # ── 第三组：混合查询（自然语言 + 术语，测试 hybrid 融合效果）──

            "基于DIN注意力模型的推荐服务如何在K8s上部署并配置Prometheus监控",
            # 期望命中: DIN模型(T4), 推荐服务API(T5), K8s部署(T7), 监控(T7)

            "推荐系统从数据采集到模型训练到线上服务的整体技术架构",
            # 期望命中: ETL(T3), 模型训练(T4), 四级架构(T5)

            "DSSM召回层和DIN排序层的特征工程需要哪些用户和物品特征",
            # 期望命中: 特征工程(T3), DSSM架构(T4), DIN(T4), 选型(T2)

            "灰度发布流程中如何用AB测试验证CTR和CVR指标",
            # 期望命中: 灰度发布(T6), AB测试(T6), 业务指标(T1)
        ]

        for item in MEMORIES:
            result = memory.add(**item)
            output_lines.append(
                f"ADDED {result.id} {result.payload.content}"
            )

        output_lines.extend([
            "=" * 80,
            "记忆检索测试",
            "=" * 80,
        ])

        for i, query in enumerate(queries, 1):
            output_lines.extend([
                "",
                "─" * 80,
                f"Query {i}: {query}",
                "─" * 80,
            ])

            for mode in ("dense", "bm25", "hybrid"):
                results = memory.search(query, mode=mode, top_k=3)
                output_lines.extend(["", f"  [{mode.upper():^6}]"])
                if not results:
                    output_lines.append("    (无结果)")
                    continue
                for rank, r in enumerate(results, 1):
                    output_lines.append(
                        f"    {rank}."
                        f"  score={r.score:.4f}"
                        f"  dense={r.dense_score}"
                        f"  bm25={r.bm25_score}"
                        f"  [{r.payload.source_task_id}]"
                        f"  {r.payload.content[:60]}..."
                    )

        output_path.write_text(
            "\n".join(output_lines) + "\n",
            encoding="utf-8",
        )

    finally:
        memory.store.close()

if __name__ == "__main__" :
    main()
