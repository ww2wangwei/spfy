import re
import asyncio
import tempfile
import os
import json
import subprocess
import urllib.request
import urllib.error
from typing import List, Dict, Optional, Tuple
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

try:
    from deep_translator import GoogleTranslator, LibreTranslator
    DEEP_TRANSLATOR_AVAILABLE = True
except ImportError:
    DEEP_TRANSLATOR_AVAILABLE = False

try:
    import googletrans
    from googletrans import Translator as GoogleTranslatorV2
    GOOGLETRANS_AVAILABLE = True
except ImportError:
    GOOGLETRANS_AVAILABLE = False

# MiniMax API 配置
MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "")
MINIMAX_BASE_URL = "https://api.minimaxi.com/v1"

# 支持的翻译模型列表
TRANSLATION_MODELS = {
    "MiniMax-abab6.5s-chat": "abab6.5s-chat",
    "MiniMax-abab6-chat": "abab6-chat",
    "MiniMax-chat": "chat",
    "Google翻译(备用)": "google"
}

# 当前选定的翻译模型
current_translation_model = "MiniMax-abab6.5s-chat"

def set_translation_model(model_name: str):
    """设置翻译模型"""
    global current_translation_model
    if model_name in TRANSLATION_MODELS:
        current_translation_model = model_name
    return current_translation_model

def get_translation_model() -> str:
    """获取当前翻译模型"""
    return current_translation_model

def update_translation_config(api_key: str, api_url: str, models: dict, current_model: str):
    """更新翻译配置"""
    global MINIMAX_API_KEY, MINIMAX_BASE_URL, TRANSLATION_MODELS, current_translation_model

    MINIMAX_API_KEY = api_key
    MINIMAX_BASE_URL = api_url
    TRANSLATION_MODELS = models.copy()
    # 添加Google翻译选项
    TRANSLATION_MODELS["Google翻译(备用)"] = "google"
    current_translation_model = current_model if current_model in TRANSLATION_MODELS else list(TRANSLATION_MODELS.keys())[0]

# 长句阈值（秒）- 超过这个时长远调用MiniMax LLM
LONGSentence_THRESHOLD = 3.0


def translate_with_minimax(text: str, max_chars: int, max_duration: float, log_callback=None) -> str:
    """
    使用 MiniMax LLM 进行主干优先精简翻译（讯飞NMT专利逻辑）

    Args:
        text: 中文原文
        max_chars: 最大字符数
        max_duration: 最大时长（秒）
        log_callback: 日志回调

    Returns:
        翻译后的英文
    """
    # 检查是否使用Google翻译作为备用
    model_key = get_translation_model()
    if model_key == "Google翻译(备用)":
        # 回退到Google翻译
        try:
            translator = GoogleTranslator(source='zh-CN', target='en')
            result = translator.translate(text)
            if log_callback:
                log_callback(f"  Google: {text[:15]}... -> {result[:25]}...")
            return result
        except Exception as e:
            if log_callback:
                log_callback(f"  Google翻译失败: {str(e)}")
            raise

    # 获取MiniMax模型名
    minimax_model = TRANSLATION_MODELS.get(model_key, "abab6.5s-chat")

    system_prompt = f"""You are a professional subtitle translator. CRITICAL: Shorten aggressively!

TRANSLATION RULES (MUST follow in order):
1. EXTRACT TRUNK: Keep only Subject + Verb + Object. DELETE all fillers, modifiers, preambles
2. SHORTEN: Use shortest natural English. Every word must earn its place
3. COLLOQUIAL: Convert to short conversational sentences, NOT书面 language
4. SIMPLIFY: Long clauses → noun phrases/prepositional phrases
5. OMIT: spoken fillers (啊, 呢, 嘛,吧, 哦), repeated ideas, hedging phrases
6. KEEP: facts, names, numbers, technical terms

FORBIDDEN:
- Long explanations or compound sentences
- Unnecessary adjectives or adverbs
- First person pronouns unless essential (I, we usually can be omitted)
- Sentence starters like "Regarding this", "Concerning that", "As for"

MAXIMUM: ≤ {max_chars} characters (about {max_duration:.1f} seconds speech)

EXAMPLES - Note the dramatic shortening:
Chinese: "我很抱歉，但是这种事情我们也没有办法控制。"
Good: "Sorry, can't control this."

Chinese: "那个时候我真的觉得特别的烦躁和郁闷。"
Good: "Really annoyed then."

Chinese: "关于这个问题的解决方案我们需要进一步的讨论。"
Good: "Need further discussion."

Chinese: "现在让我们来学习电气制图认证课程。"
Good: "Learn electrical drafting."

OUTPUT: ONLY the final English subtitle text. No explanations, no notes, no reasoning, no <think> tags."""

    user_prompt = f"""Translate Chinese to English.
CRITICAL: ≤ {max_chars} characters!

Chinese: {text}
English:"""

    payload = {
        "model": minimax_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 200
    }

    try:
        req = urllib.request.Request(
            f"{MINIMAX_BASE_URL}/chat/completions",
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {MINIMAX_API_KEY}'
            },
            method='POST'
        )

        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            translated = strip_reasoning_artifacts(result['choices'][0]['message']['content'])

            if looks_like_reasoning(translated):
                retry_payload = {
                    "model": minimax_model,
                    "messages": [
                        {"role": "system", "content": system_prompt + "\n\nCRITICAL: Output ONLY the final translated subtitle text. Do NOT include reasoning, analysis, explanations, labels, or <think> tags."},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.2,
                    "max_tokens": 200
                }

                req2 = urllib.request.Request(
                    f"{MINIMAX_BASE_URL}/chat/completions",
                    data=json.dumps(retry_payload).encode('utf-8'),
                    headers={
                        'Content-Type': 'application/json',
                        'Authorization': f'Bearer {MINIMAX_API_KEY}'
                    },
                    method='POST'
                )

                with urllib.request.urlopen(req2, timeout=30) as response2:
                    result2 = json.loads(response2.read().decode('utf-8'))
                    translated = strip_reasoning_artifacts(result2['choices'][0]['message']['content'])

            if looks_like_reasoning(translated):
                raise Exception("AI返回了推理内容，未得到有效翻译")

            if log_callback:
                log_callback(f"  {model_key}: {text[:15]}... -> {translated[:25]}...")

            return translated

    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else ''
        if log_callback:
            log_callback(f"  {model_key} HTTP {e.code}: {error_body[:200]}")
        raise Exception(f"{model_key} HTTP {e.code}: {error_body[:200]}")
    except Exception as e:
        if log_callback:
            log_callback(f"  {model_key} error: {str(e)}")
        raise


def contains_chinese(text: str) -> bool:
    """检测文本是否包含中文字符"""
    for char in text:
        if '\u4e00' <= char <= '\u9fff':
            return True
    return False


REASONING_PATTERNS = [
    r'(?i)<\s*think\s*>',
    r'(?i)</\s*think\s*>',
    r'(?i)^let\s+me\s+translate\b',
    r'(?i)^the\s+user\s+wants\s+me\b',
    r'(?i)^i\s+need\s+to\s+translate\b',
    r'(?i)^to\s+translate\s+a\s+chinese\s+subtitle\b',
    r'(?i)^this\s+is\s+(a\s+)?(?:very\s+)?short\s+chinese\s+subtitle\b',
    r'(?i)^this\s+is\s+a\s+short\s+chinese\s+subtitle\s+that\s+needs\b',
    r'(?i)^this\s+is\s+(a\s+)?technical\b',
    r'(?i)^original\s*:',
    r'(?i)^chinese\s*:',
    r'(?i)^english\s*:',
    r'(?i)^shortening\b',
    r'(?i)^let\s+me\b',
    r'(?i)^this\s+is\s+already\b',
    r'(?i)^or\s+even\s+shorter\b',
    r'(?i)^count\s*:',
    r'(?i)^that\'?s\s+\d+\s+characters\b',
    r'(?i)^this\s+works\b',
    r'(?i)^actually\b',
    r'(?i)^alternative\s*:',
    r'(?i)^character\b',
    r'(?i)^this\s+seems\b',
    r'(?i)^this\s+is\s+basically\b',
    r'(?i)^\d+\.\s*(extract|shorten|colloquial|simplify|omit|keep)\b',
]


def _is_reasoning_line(line: str) -> bool:
    """判断一行是否像模型的思考/提示词残留。"""
    stripped = line.strip()
    if not stripped:
        return False
    return any(re.search(pattern, stripped) for pattern in REASONING_PATTERNS)


def strip_reasoning_artifacts(text: str) -> str:
    """清理模型推理痕迹，只保留最终翻译文本。"""
    if not text:
        return text

    cleaned = text.replace('\r\n', '\n').replace('\r', '\n').strip()

    # 如果模型把最终答案放在标签后面，优先提取最后一个明确答案。
    answer_patterns = [
        r'(?is)(?:final\s+answer|final|english\s+translation|translation|english)\s*[:：]\s*(.+)$',
    ]
    for pattern in answer_patterns:
        match = re.search(pattern, cleaned)
        if match:
            cleaned = match.group(1).strip()
            break

    # 先移除成对 think 标签内容
    cleaned = re.sub(r'(?is)<\s*think\s*>.*?<\s*/\s*think\s*>', ' ', cleaned)
    # 有些推理模型会返回未闭合的 <think>，这种内容不能进入字幕
    cleaned = re.sub(r'(?is)<\s*think\s*>.*$', ' ', cleaned)
    # 再去掉孤立标签本身
    cleaned = re.sub(r'(?is)<\s*/?\s*think\s*>', ' ', cleaned)

    lines = []
    for raw_line in cleaned.split('\n'):
        line = raw_line.strip()
        if not line:
            continue
        if _is_reasoning_line(line):
            continue
        lines.append(line)

    cleaned = ' '.join(lines).strip()
    cleaned = re.sub(r'^(English:)\s*', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'^["""''「」『』【】]+', '', cleaned)
    trailing_reasoning_pattern = (
        r"\s*[\"'“”]?\s*(?:[-–—]\s*)?(?:Shortening\b|This\s+is\s+already\b|Let\s+me\b|"
        r"Or\s+even\s+shorter\b|Count\s*:|That'?s\s+\d+\s+characters\b|"
        r"This\s+is\s+\d+\s+characters\b|This\s+works\b|This\s+is\s+clean\b|"
        r"This\s+is\s+concise\b|well\s+under\s+\d+\b|under\s+\d+\b|"
        r"\d+\s+characters\b|characters\s*[✓-]|"
        r"Actually\b|Alternative\s*:|Character\b|This\s+seems\b|"
        r"This\s+is\s+basically\b|sounds\s+a\b|"
        r"I\s+(?:need|should|will)\b|The\s+user\s+wants\s+me\b|"
        r"This\s+(?:sentence|subtitle|translation)\b).*$"
    )
    cleaned = re.sub(trailing_reasoning_pattern, '', cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r'\s*["\'“”]?\s*[-–—]\s*This\s+is\s+\d+.*$', '', cleaned, flags=re.IGNORECASE | re.DOTALL)
    # 模型常把候选翻译接在第二个引号后面，只保留第一个候选前的正文。
    cleaned = re.sub(r'(?s)^(.+?)["”]\s+["“].*$', r'\1', cleaned)
    cleaned = re.sub(r'(?s)^(.+?)["”]\s*(?:[-–—]\s*)?["“].*$', r'\1', cleaned)
    cleaned = re.sub(r'(?is)\s+(?:Alternative\s*:|Actually\b|This\s+seems\b|This\s+is\s+basically\b|Character\b|That\'?s\s+shorter\b).*$',
                     '', cleaned)
    cleaned = re.sub(r'(?is)["”]\s*(?:[-–—]\s*)?(?:It\'?s|That\'?s|This\s+is|Change|Click|Press|Hold|Tap|Select|Use)\b.*$',
                     '', cleaned)
    # 如果模型给了多个候选翻译，只保留第一个候选。
    cleaned = re.sub(r'\s+(?:or|OR)\s+["“].*$', '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'^\s*[-–—]\s*["“](.*?)["”]\s*[-–—].*$', r'\1', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'["""''「」『』【】]+$', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def has_chinese_residue(text: str) -> bool:
    """判断英文翻译中是否有明显中文残留。"""
    if not text:
        return False
    chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
    if not chinese_chars:
        return False
    # 单个中文符号/专名残留不直接判死，多个中文字符才认为翻译失败。
    return len(chinese_chars) >= 2


def looks_like_reasoning(text: str) -> bool:
    """判断模型输出是否仍然像思考过程，而不是翻译结果。"""
    if not text or not text.strip():
        return True

    stripped = text.strip()
    if any(re.search(pattern, stripped) for pattern in REASONING_PATTERNS):
        return True

    alpha_count = len(re.findall(r'[A-Za-z]', stripped))
    word_count = len(re.findall(r'\b[A-Za-z]+\b', stripped))
    if alpha_count == 0:
        return True

    if re.search(r'(?i)\b(the\s+user\s+wants\s+me|let\s+me(?:\s+\w+)?|i\s+need\s+to\s+translate|shortening|well\s+under\s+\d+|or\s+even\s+shorter|characters\s*[✓-]|count\s*:)\b', stripped):
        return True

    return word_count >= 5 and stripped.endswith(':')

def clean_text_for_translation(text: str) -> str:
    """清理文本，准备翻译"""
    # 移除多余空格和换行
    text = text.strip()
    text = re.sub(r'\s+', ' ', text)
    return text


def translate_with_google_timeout(text: str, timeout: int = 10) -> str:
    """使用Google翻译，避免备用翻译长时间卡住。"""
    def _translate():
        google_translator = GoogleTranslator(source='zh-CN', target='en')
        return google_translator.translate(text)

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_translate)
    try:
        return future.result(timeout=timeout)
    except FutureTimeoutError:
        future.cancel()
        raise TimeoutError(f"Google翻译超过{timeout}秒未响应")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

def make_translation_prompt(text: str, target_lang: str = "en") -> str:
    """
    创建翻译提示词，引导更自然、符合目标语言阅读习惯的翻译
    
    注意：此函数返回的提示词仅供翻译引擎内部使用，
    不会作为文本的一部分被翻译，避免提示词混入翻译结果
    
    Args:
        text: 原始文本
        target_lang: 目标语言
    
    Returns:
        纯文本内容（不添加提示词前缀，避免提示词被翻译）
    """
    # 直接返回纯文本，不添加提示词前缀
    # 提示词前缀会被翻译引擎当成文本一起翻译，导致结果混乱
    return text

def post_process_english(text: str) -> str:
    """
    后处理英文字幕，确保符合英文阅读习惯
    
    英文阅读习惯特点：
    1. 首字母大写，句末用句号
    2. 使用常见的英语表达习惯
    3. 避免过长的句子
    4. 正确使用标点符号
    5. 专业术语使用标准表达
    
    Args:
        text: 翻译后的英文文本
    
    Returns:
        优化后的英文文本
    """
    if not text:
        return text
    
    # 标准化标点
    text = text.replace('。', '.')
    text = text.replace('，', ',')
    text = text.replace('；', ';')
    text = text.replace('！', '!')
    text = text.replace('？', '?')
    text = text.replace('、', ', ')
    
    # 确保句末有标点
    text = text.strip()
    if text and text[-1] not in '.!?:;':
        text += '.'
    
    # 首字母大写
    sentences = re.split(r'(?<=[.!?])\s+', text)
    capitalized = []
    for sentence in sentences:
        if sentence:
            # 首字母大写
            sentence = sentence[0].upper() + sentence[1:]
            capitalized.append(sentence)
    text = ' '.join(capitalized)
    
    # 修复常见的翻译问题
    text = fix_common_translation_issues(text)
    
    # 去除多余空格
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

def fix_common_translation_issues(text: str) -> str:
    """
    修复常见的翻译问题，使英文更自然
    
    Args:
        text: 翻译后的英文文本
    
    Returns:
        修复后的英文文本
    """
    # 常见的中式英语表达修正
    fixes = {
        # 被动语态优化
        r'\bbe\s+very\s+important\b': 'is very important',
        r'\bwe\s+can\s+see\b': 'we can see that',
        r'\blet\s+us\s+look\s+at\b': 'let us look at',
        
        # 专业术语标准化
        r'\bschematic\s+diagram\b': 'schematic',
        r'\belectrical\s+drawing\b': 'electrical diagram',
        r'\btext\s+symbol\b': 'letter symbol',
        
        # 动词时态修正
        r'\bis\s+consist\s+of\b': 'consists of',
        r'\bare\s+consist\s+of\b': 'consist of',
        
        # 冠词修正
        r'\buse\s+the\s+a\b': 'use a',
        r'\buse\s+the\s+an\b': 'use an',
        
        # 介词修正
        r'\bin\s+the\s+field\s+of\b': 'in the field of',
        r'\bon\s+the\s+back\s+of\b': 'on the rear of',
    }
    
    for pattern, replacement in fixes.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    
    return text

def split_long_sentence(text: str, max_chars: int = 60) -> List[str]:
    """
    智能分割长句子，适合中英翻译
    
    中文特点：
    - 逗号、句号、分号是主要断句点
    - 长句需要在语义完整的前提下分割
    
    Args:
        text: 原始文本
        max_chars: 最大字符数限制
    
    Returns:
        分割后的句子列表
    """
    if len(text) <= max_chars:
        return [text]
    
    sentences = []
    current = []
    current_len = 0
    
    # 中文标点断句优先级
    split_patterns = [
        r'。',    # 句号
        r'！',    # 感叹号
        r'？',    # 问号
        r'；',    # 分号
        r'，',    # 逗号
        r'、',    # 顿号
    ]
    
    # 尝试按语义分割
    segments = [text]
    
    for pattern in split_patterns:
        new_segments = []
        for seg in segments:
            if len(seg) > max_chars:
                parts = re.split(f'({pattern})', seg)
                combined = []
                for i, part in enumerate(parts):
                    if part in pattern.replace('\\', ''):
                        if combined:
                            combined[-1] += part
                        else:
                            combined.append(part)
                    else:
                        combined.append(part)
                new_segments.extend([s for s in combined if s.strip()])
            else:
                new_segments.append(seg)
        segments = new_segments
    
    # 合并过短的片段（少于5个字符）
    result = []
    buffer = ""
    for seg in segments:
        if len(buffer) + len(seg) <= max_chars:
            buffer += seg
        else:
            if buffer:
                result.append(buffer.strip())
            buffer = seg
    if buffer:
        result.append(buffer.strip())
    
    return result

def merge_short_sentences(segments: List[Dict], min_duration: float = 1.0) -> List[Dict]:
    """
    合并过短的字幕段，确保TTS朗读流畅
    
    Args:
        segments: 字幕段列表
        min_duration: 最小时长（秒），小于此值的会被合并
    
    Returns:
        合并后的字幕段列表
    """
    if not segments:
        return segments
    
    result = []
    current_group = [segments[0]]
    current_duration = segments[0]['end'] - segments[0]['start']
    
    for seg in segments[1:]:
        seg_duration = seg['end'] - seg['start']
        
        # 如果当前组太短且下一段也短，则合并
        if current_duration < min_duration and seg_duration < min_duration:
            current_group.append(seg)
            current_duration += seg_duration
        else:
            # 合并当前组
            if len(current_group) > 1:
                merged = {
                    'index': current_group[0]['index'],
                    'start': current_group[0]['start'],
                    'end': current_group[-1]['end'],
                    'text': ' '.join(s['text'] for s in current_group)
                }
                result.append(merged)
            else:
                result.append(current_group[0])
            
            current_group = [seg]
            current_duration = seg_duration
    
    # 处理最后一组
    if len(current_group) > 1:
        merged = {
            'index': current_group[0]['index'],
            'start': current_group[0]['start'],
            'end': current_group[-1]['end'],
            'text': ' '.join(s['text'] for s in current_group)
        }
        result.append(merged)
    elif current_group:
        result.append(current_group[0])
    
    return result

def split_english_by_punctuation(text: str, max_chars: int = 80) -> List[str]:
    """
    按英文标点符号自然断句分段

    Args:
        text: 英文文本
        max_chars: 每段最大字符数

    Returns:
        分割后的英文句子列表
    """
    if not text or len(text) <= max_chars:
        return [text] if text else []

    # 英文断句符号
    split_patterns = [
        r'\.\s+',      # 句号后跟空格
        r';\s+',       # 分号后跟空格
        r',\s+',       # 逗号后跟空格
        r'!\s+',       # 感叹号后跟空格
        r'\?\s+',      # 问号后跟空格
    ]

    parts = [text]

    for pattern in split_patterns:
        new_parts = []
        for part in parts:
            if len(part) > max_chars:
                split_result = re.split(f'({pattern})', part)
                combined = []
                for item in split_result:
                    if item in ('.', ';', ',', '!', '?') or re.match(pattern, item):
                        if combined:
                            combined[-1] += item
                        else:
                            combined.append(item)
                    else:
                        combined.append(item)
                new_parts.extend([s.strip() for s in combined if s.strip()])
            else:
                new_parts.append(part)
        parts = new_parts

    # 如果分割后仍有超过max_chars的片段，强制按单词数分割
    final_parts = []
    for part in parts:
        while len(part) > max_chars:
            # 找一个合适的位置分割（约max_chars处）
            split_idx = max_chars
            # 向前找空格
            for i in range(max_chars, max(0, max_chars - 20), -1):
                if part[i:i+1].isspace():
                    split_idx = i
                    break
            final_parts.append(part[:split_idx].strip())
            part = part[split_idx:].strip()
        if part:
            final_parts.append(part)

    return final_parts



def _is_svo_boundary(text: str, full_text: str, pos: int) -> bool:
    """
    判断是否SVO主谓结构边界
    SVO: 主语+谓语+宾语的完整结构
    """
    # 简单判断：如果前面是完整动词短语，可能需要断开
    return False


def _split_long_chunk(text: str, max_chars: int) -> List[str]:
    """
    将长chunk拆分为≤max_chars的片段
    在逗号/空格处断开，避免拆单词
    """
    if len(text) <= max_chars:
        return [text]
    
    result = []
    current = ''
    words = text.split(' ')
    
    for word in words:
        if len(current) + len(word) + 1 <= max_chars:
            current = (current + ' ' + word).strip()
        else:
            if current:
                result.append(current)
            # 尝试在逗号处断开
            if ',' in word or '，' in word:
                parts = re.split(r'([，,])', word)
                for part in parts:
                    if len(part) <= max_chars:
                        if part:
                            result.append(part)
                    else:
                        # 仍然太长，继续拆分
                        for i in range(0, len(part), max_chars):
                            result.append(part[i:i+max_chars])
            else:
                # 无法在单词中断开，强制按max_chars截断
                for i in range(0, len(word), max_chars):
                    result.append(word[i:i+max_chars])
            current = ''
    
    if current:
        result.append(current)
    
    return result




def segment_chinese_pro(text: str, max_chars: int = 16) -> list:
    """
    遵循专业字幕规范的Chunk分段
    
    规则：
    1. 。！？强制切分新Chunk
    2. 逗号仅在>18汉字时切分
    3. 引号括号内整体不拆分
    4. 中文单行<=16字
    5. 三字内短句就近合并
    """
    if not text:
        return [{'text': '', 'is_quote': False}]
    
    # 强制断句符
    force_break = set('。！？')
    # 软断句符（逗号）
    soft_break = set('，,')
    
    segments = []
    current = ''
    
    for char in text:
        if char in force_break:
            if current:
                segments.append(current.strip())
                current = ''
        elif char in soft_break:
            if len(current) >= 18:
                segments.append(current.strip())
                current = ''
            else:
                current += char
        else:
            current += char
    
    if current.strip():
        segments.append(current.strip())
    
    # 合并三字以内短句
    merged = []
    buffer = ''
    for seg in segments:
        if len(seg) <= 3:
            buffer = (buffer + ' ' + seg).strip()
        else:
            if buffer:
                merged.append(buffer)
            buffer = seg
    if buffer:
        merged.append(buffer)
    
    # 限制每chunk<=max_chars
    final = []
    for chunk in merged:
        if len(chunk) <= max_chars:
            final.append({'text': chunk, 'is_quote': False})
        else:
            # 在空格处拆分
            words = chunk.split(' ')
            sub_chunk = ''
            for word in words:
                if len(sub_chunk) + len(word) + 1 <= max_chars:
                    sub_chunk = (sub_chunk + ' ' + word).strip()
                else:
                    if sub_chunk:
                        final.append({'text': sub_chunk, 'is_quote': False})
                    sub_chunk = word
            if sub_chunk:
                final.append({'text': sub_chunk, 'is_quote': False})
    
    return final



class TranslatorEngine:
    """翻译引擎，支持中英互译"""
    
    def __init__(self):
        self.source_lang = "zh-CN"
        self.target_lang = "en"
        self.max_retries = 3  # 最大重试次数
    
    def set_languages(self, source: str, target: str):
        """设置源语言和目标语言"""
        lang_map = {
            "中文": "zh-CN",
            "English": "en",
            "Japanese": "ja",
            "Korean": "ko",
            "French": "fr",
            "German": "de",
            "Spanish": "es",
            "Russian": "ru",
            "Portuguese": "pt",
            "Italian": "it"
        }
        self.source_lang = lang_map.get(source, source)
        self.target_lang = lang_map.get(target, target)
    
    def load_srt(self, srt_path: str) -> List[Dict]:
        """加载SRT文件"""
        segments = []
        try:
            with open(srt_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            blocks = content.strip().split('\n\n')
            for block in blocks:
                lines = block.strip().split('\n')
                if len(lines) >= 3:
                    time_match = re.match(
                        r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})',
                        lines[1]
                    )
                    if time_match:
                        start_time = self._time_str_to_seconds(time_match.group(1))
                        end_time = self._time_str_to_seconds(time_match.group(2))
                        text = '\n'.join(lines[2:]).strip()
                        segments.append({
                            'index': int(lines[0]),
                            'start': start_time,
                            'end': end_time,
                            'text': text
                        })
        except Exception as e:
            raise Exception(f"加载SRT文件失败: {str(e)}")
        
        return segments
    
    def _time_str_to_seconds(self, time_str: str) -> float:
        """将SRT时间字符串转换为秒数"""
        try:
            time_str = time_str.replace(',', '.')
            parts = time_str.split(':')
            if len(parts) == 3:
                hours = float(parts[0])
                minutes = float(parts[1])
                seconds = float(parts[2])
                return hours * 3600 + minutes * 60 + seconds
        except:
            pass
        return 0.0
    
    def translate_srt(self, srt_path: str, target_lang: str = "en",
                     speed_multiplier: float = 1.0,
                     progress_callback=None, log_callback=None) -> str:
        """
        翻译SRT字幕文件（基于TTS时长重新计算时间戳）

        流程：
        1. 加载中文SRT
        2. 翻译每段中文为英文
        3. 按英文标点断句重新分段
        4. TTS生成每段音频，记录时长
        5. 从中文第一段的start开始，用TTS时长重新计算英文时间戳
        6. 生成英文SRT

        时间戳计算：
        - 英文第一段的start = 中文第一段的start（同步起点）
        - 英文段N的start = 英文段(N-1)的end
        - 英文段N的end = 英文段N的start + TTS时长N

        Args:
            srt_path: 字幕文件路径
            target_lang: 目标语言（默认英文）
            speed_multiplier: 时间轴倍数
            progress_callback: 进度回调
            log_callback: 日志回调

        Returns:
            翻译后的SRT文件路径
        """
        if not DEEP_TRANSLATOR_AVAILABLE:
            raise Exception("翻译引擎未安装，请运行: pip install deep-translator")

        if log_callback:
            log_callback(f"开始翻译字幕（TTS时长重算时间戳模式）...")
            log_callback(f"源文件: {srt_path}")
            log_callback(f"目标语言: {target_lang}")

        # 加载字幕
        if progress_callback:
            progress_callback(5, 100, "加载字幕文件...")

        cn_segments = self.load_srt(srt_path)

        if log_callback:
            log_callback(f"加载完成: {len(cn_segments)} 个中文字幕段")

        if progress_callback:
            progress_callback(10, 100, "初始化翻译引擎...")

        # 选择最佳翻译器
        translator, translator_type = self._select_best_translator(target_lang, log_callback)

        if log_callback:
            log_callback(f"  使用翻译器: {translator_type}")

        # 导入TTS引擎
        from .tts_engine import TTSEngine
        tts_engine = TTSEngine()
        voice = "en-US-JennyNeural"

        # 同步起点：中文第一段的start
        sync_start = cn_segments[0]['start'] if cn_segments else 0.0

        # 第一阶段：翻译所有中文段落为英文
        if log_callback:
            log_callback(f"开始翻译...")

        translated_texts = []
        total = len(cn_segments)

        for i, segment in enumerate(cn_segments):
            if progress_callback:
                progress = int(10 + (i / total) * 40)
                progress_callback(progress, 100, f"翻译中 {i+1}/{total}...")

            # 检查是否请求停止
            from . import task_manager
            if task_manager.check_stop():
                if log_callback:
                    log_callback(f"⚠ 用户停止翻译，终止任务")
                raise Exception("用户停止翻译")

            try:
                original_text = segment['text']
                cn_duration = segment['end'] - segment['start']

                # 计算最大允许字符数（约10字符/秒，英文比中文紧凑）
                max_chars = int(cn_duration * 10)

                # 所有段落都使用 MiniMax LLM 约束翻译
                # 关键：告诉LLM英文必须在max_chars字符内表达完整意思
                if log_callback:
                    log_callback(f"  段{i+1}: 约束翻译(max_chars={max_chars}, duration={cn_duration:.1f}s)")

                try:
                    translated_text = translate_with_minimax(
                        original_text,
                        max_chars=max_chars,
                        max_duration=cn_duration,
                        log_callback=log_callback
                    )
                except Exception as llm_err:
                    if log_callback:
                        log_callback(f"  {get_translation_model()} 失败，回退到Google翻译: {str(llm_err)}")
                    # 回退到 Google 翻译，但做裁剪
                    translated_text = self._translate_text_with_retry(
                        translator, original_text, log_callback, translator_type
                    )
                    translated_text = self._clean_translation_result(translated_text, original_text)
                    # 裁剪到最大字符数
                    if len(translated_text) > max_chars:
                        translated_text = translated_text[:max_chars].rsplit(' ', 1)[0].strip()

                # 英文后处理
                if target_lang == "en":
                    translated_text = post_process_english(translated_text)

                translated_texts.append(translated_text)
                time.sleep(0.2)

            except Exception as e:
                if log_callback:
                    log_callback(f"  ✗ 翻译失败 [{i+1}]: {str(e)}")
                translated_texts.append(f"[翻译失败] {segment['text']}")

        # 第二阶段：按英文标点断句，TTS测试每段时长，重新计算时间戳
        if log_callback:
            log_callback(f"开始TTS测试和重新计算时间戳...")

        en_segments = []
        current_time = sync_start
        en_index = 1

        for i, (cn_seg, en_text) in enumerate(zip(cn_segments, translated_texts)):
            if progress_callback:
                progress = 50 + int((i / total) * 40)
                progress_callback(progress, 100, f"TTS测试 {i+1}/{total}...")

            # 检查是否请求停止
            if task_manager.check_stop():
                if log_callback:
                    log_callback(f"⚠ 用户停止翻译，终止任务")
                raise Exception("用户停止翻译")

            # 按英文标点断句
            en_chunks = segment_chinese_pro(en_text, max_chars=16)

            if log_callback and len(en_chunks) > 1:
                log_callback(f"  中文段{i+1}: 分割为{len(en_chunks)}个英文子句")

            for j, chunk in enumerate(en_chunks):
                # TTS生成测试音频
                temp_path = os.path.join(tempfile.gettempdir(), f"tts_en_{en_index:04d}.mp3")

                try:
                    asyncio.run(tts_engine.synthesize_segment(chunk, voice, temp_path))
                    tts_duration = tts_engine._get_audio_duration(temp_path)
                except Exception as e:
                    if log_callback:
                        log_callback(f"    TTS失败 [{j+1}]: {str(e)}")
                    tts_duration = len(chunk) / 8.0
                finally:
                    if os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except:
                            pass

                # 计算时间戳
                en_start = current_time
                en_end = en_start + tts_duration

                en_segments.append({
                    'index': en_index,
                    'start': en_start,
                    'end': en_end,
                    'text': chunk
                })

                current_time = en_end
                en_index += 1

        if progress_callback:
            progress_callback(90, 100, "保存翻译文件...")

        # 生成翻译后的SRT
        output_path = self._save_translated_srt(srt_path, en_segments, target_lang)

        if progress_callback:
            progress_callback(100, 100, "翻译完成")

        if log_callback:
            log_callback(f"✓ 翻译完成（TTS时长重算时间戳模式）")
            log_callback(f"  中文段数: {total}")
            log_callback(f"  英文段数: {len(en_segments)}")
            log_callback(f"  起点同步: {sync_start:.3f}s")
            log_callback(f"  输出文件: {output_path}")

        return output_path
    
    def _select_best_translator(self, target_lang: str, log_callback=None):
        """
        选择最佳翻译器，优先使用更适合意译的引擎
        
        Args:
            target_lang: 目标语言
            log_callback: 日志回调
        
        Returns:
            (translator, translator_type) 元组
        """
        # 优先使用 googletrans（更自然的翻译结果）
        if GOOGLETRANS_AVAILABLE:
            try:
                translator = GoogleTranslatorV2()
                return translator, "googletrans (v2)"
            except Exception as e:
                if log_callback:
                    log_callback(f"    googletrans初始化失败: {str(e)}")
        
        # 回退到 deep_translator 的 GoogleTranslator
        if DEEP_TRANSLATOR_AVAILABLE:
            try:
                translator = GoogleTranslator(source='zh-CN', target=target_lang)
                return translator, "deep_translator (Google)"
            except Exception as e:
                if log_callback:
                    log_callback(f"    deep_translator初始化失败: {str(e)}")
        
        raise Exception("未找到可用的翻译引擎")
    
    def _clean_translation_result(self, translated_text: str, original_text: str) -> str:
        """
        清理翻译结果，只保留英文翻译内容
        
        问题：翻译引擎会把提示词也当成文本翻译，导致输出包含翻译说明
        解决：只提取英文翻译内容，去除所有提示词、说明文字等
        
        Args:
            translated_text: 翻译结果
            original_text: 原始文本
        
        Returns:
            清理后的翻译结果（纯英文）
        """
        if not translated_text:
            return translated_text
        
        translated_text = strip_reasoning_artifacts(translated_text)

        # 去除所有提示词相关的文本
        prompt_patterns = [
            r'(?i)translate\s+to\s+english[^:]*:',
            r'(?i)translate\s+to\s+english[^:]*text\s*:',
            r'(?i)translate\s+to\s+natural[^:]*:',
            r'(?i)natural,\s*fluent\s+english[^:]*:',
            r'(?i)common\s+english\s+phrasing[^:]*:',
            r'(?i)concise\s+and\s+easy\s+to\s+read[^:]*:',
            r'(?i)text\s*[:：]\s*',
            r'(?i)translation\s*[:：]\s*',
            r'(?i)english\s+translation\s*[:：]\s*',
        ]
        
        for pattern in prompt_patterns:
            translated_text = re.sub(pattern, '', translated_text, flags=re.DOTALL)
        
        # 去除多余空格和引号
        translated_text = translated_text.strip()
        translated_text = translated_text.strip('"')
        translated_text = translated_text.strip("'")
        
        # 只保留英文内容（去除中文）
        if contains_chinese(translated_text):
            # 按中文字符分割，只取英文部分
            parts = re.split(r'[\u4e00-\u9fff]+', translated_text)
            translated_text = ' '.join([p.strip() for p in parts if p.strip()])
        
        return translated_text.strip()
    
    def _translate_text_with_retry(self, translator, text: str, log_callback=None, 
                                   translator_type: str = "deep_translator") -> str:
        """带重试机制的翻译，支持多种翻译器类型"""
        if not text.strip():
            return text
        
        last_error = None
        for attempt in range(self.max_retries):
            try:
                result = self._translate_text(translator, text, translator_type)
                return result
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    time.sleep(0.5)  # 重试前等待
                    if log_callback:
                        log_callback(f"    重试翻译 ({attempt + 2}/{self.max_retries})...")
        
        raise last_error
    
    def _translate_text(self, translator, text: str, translator_type: str = "deep_translator") -> str:
        """翻译单个文本，支持多种翻译器类型"""
        if not text.strip():
            return text
        
        # 处理换行符，分段翻译
        lines = text.split('\n')
        translated_lines = []
        
        for line in lines:
            if line.strip():
                # 移除特殊字符干扰
                clean_line = line.strip()
                
                # 根据翻译器类型调用不同的方法
                if translator_type == "googletrans (v2)":
                    result = translator.translate(clean_line, dest='en').text
                else:
                    result = translator.translate(clean_line)
                
                translated_lines.append(result)
            else:
                translated_lines.append('')
        
        return '\n'.join(translated_lines)
    
    def _save_translated_srt(self, original_path: str, segments: List[Dict],
                            target_lang: str) -> str:
        """保存翻译后的SRT文件"""
        from pathlib import Path
        
        # 生成输出文件名
        lang_suffix = {
            "en": "_EN",
            "ja": "_JA",
            "ko": "_KO",
            "fr": "_FR",
            "de": "_DE",
            "es": "_ES",
            "ru": "_RU"
        }.get(target_lang, f"_{target_lang.upper()}")
        
        output_path = Path(original_path).parent / f"{Path(original_path).stem}{lang_suffix}.srt"
        
        with open(output_path, 'w', encoding='utf-8') as f:
            for segment in segments:
                f.write(f"{segment['index']}\n")
                start_str = self._seconds_to_time_str(segment['start'])
                end_str = self._seconds_to_time_str(segment['end'])
                f.write(f"{start_str} --> {end_str}\n")
                f.write(f"{segment['text']}\n")
                f.write("\n")
        
        return str(output_path)
    
    def _seconds_to_time_str(self, seconds: float) -> str:
        """将秒数转换为SRT时间格式（HH:MM:SS,mmm）"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        milliseconds = int((secs - int(secs)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{int(secs):02d},{milliseconds:03d}"


def translate_srt_with_video_sync(audio_path: str, srt_path: str, target_lang: str = "en",
                               progress_callback=None, log_callback=None) -> str:
    """
    基于音频检测时间戳的翻译

    流程：
    1. Faster Whisper识别音频 → 获取每段实际时间点
    2. 加载中文SRT，翻译成英文
    3. 将英文句子匹配到检测到的时间戳
    4. 生成英文SRT

    Args:
        audio_path: 音频文件路径（MP3）
        srt_path: 中文字幕文件路径
        target_lang: 目标语言
        progress_callback: 进度回调
        log_callback: 日志回调

    Returns:
        英文SRT文件路径
    """
    if log_callback:
        log_callback("=" * 50)
        log_callback("基于音频时间戳的翻译模式")
        log_callback("=" * 50)

    # 步骤1: Faster Whisper识别音频
    if progress_callback:
        progress_callback(5, 100, "Whisper识别音频...")

    # 步骤2: Faster Whisper识别音频获取实际时间戳
    if progress_callback:
        progress_callback(15, 100, "Faster Whisper识别音频...")

    if log_callback:
        log_callback("步骤2: Faster Whisper识别音频获取时间戳...")

    try:
        from faster_whisper import WhisperModel

        if log_callback:
            log_callback("  加载Faster Whisper模型...")

        # 加载模型（CPU模式更快）
        model = WhisperModel("small", device="cpu", compute_type="int8")

        if log_callback:
            log_callback("  开始识别...")

        # 识别音频，获取每段的时间戳
        segments, info = model.transcribe(
            audio_path,
            language="zh",  # 假设原音频是中文
            beam_size=5,
            vad_filter=True
        )

        if log_callback:
            log_callback(f"  检测到语言: {info.language} (置信度: {info.language_probability:.2f})")

        # 提取每段的时间戳
        video_timestamps = []
        for seg in segments:
            video_timestamps.append({
                'start': seg.start,
                'end': seg.end,
                'text': seg.text.strip()
            })

        if log_callback:
            log_callback(f"  检测到 {len(video_timestamps)} 段")

        # 清理模型
        del model

    except Exception as e:
        if log_callback:
            log_callback(f"✗ Whisper识别失败: {str(e)}")
        raise

    # 步骤3: 加载中文SRT并翻译
    if progress_callback:
        progress_callback(40, 100, "翻译中文字幕...")

    if log_callback:
        log_callback("步骤3: 翻译中文字幕...")

    # 加载中文SRT
    cn_segments = translator_engine.load_srt(srt_path)
    if log_callback:
        log_callback(f"  加载了 {len(cn_segments)} 段中文字幕")

    # 翻译每段中文
    translated_texts = []
    for i, seg in enumerate(cn_segments):
        if progress_callback:
            progress = 40 + int((i / len(cn_segments)) * 30)
            progress_callback(progress, 100, f"翻译中 {i+1}/{len(cn_segments)}...")

        try:
            # 使用MiniMax LLM约束翻译
            cn_duration = seg['end'] - seg['start']
            max_chars = int(cn_duration * 10)

            translated = translate_with_minimax(
                seg['text'],
                max_chars=max_chars,
                max_duration=cn_duration,
                log_callback=log_callback
            )
            translated_texts.append(translated)

        except Exception as e:
            if log_callback:
                log_callback(f"  翻译失败 [{i+1}]: {str(e)}")
            # 回退到Google翻译
            try:
                translated = translator_engine._translate_text_with_retry(
                    translator_engine._select_best_translator(target_lang, log_callback)[0],
                    seg['text'],
                    log_callback,
                    translator_engine._select_best_translator(target_lang, log_callback)[1]
                )
                translated = translator_engine._clean_translation_result(translated, seg['text'])
            except:
                translated = f"[翻译失败] {seg['text']}"
            translated_texts.append(translated)

    # 步骤4: 将英文句子匹配到视频时间戳
    if progress_callback:
        progress_callback(75, 100, "匹配时间戳...")

    if log_callback:
        log_callback("步骤4: 匹配英文到视频时间戳...")

    # 计算视频总时长
    video_total = video_timestamps[-1]['end'] if video_timestamps else 0

    # 创建英文SRT段
    en_segments = []
    current_en_index = 1

    for i, (cn_seg, en_text) in enumerate(zip(cn_segments, translated_texts)):
        # 找到对应的视频时间戳
        cn_start = cn_seg['start']
        cn_end = cn_seg['end']

        # 在video_timestamps中找重叠的部分
        matching_video_segs = []
        for v_seg in video_timestamps:
            # 如果视频段和中文字幕段有重叠
            if v_seg['end'] > cn_start and v_seg['start'] < cn_end:
                matching_video_segs.append(v_seg)

        if matching_video_segs:
            # 使用匹配到的视频时间戳
            v_start = matching_video_segs[0]['start']
            v_end = matching_video_segs[-1]['end']
        else:
            # 如果没有匹配，使用中文字幕的时间戳
            v_start = cn_start
            v_end = cn_end

        # 分割英文文本
        en_chunks = segment_chinese_pro(en_text, max_chars=16)

        if log_callback and len(en_chunks) > 1:
            log_callback(f"  中文段{i+1}: 分割为{len(en_chunks)}个英文子句")

        # 计算每个英文子句的时长
        total_en_chars = sum(len(c) for c in en_chunks)
        if total_en_chars == 0:
            continue

        v_duration = v_end - v_start
        current_pos = v_start

        for j, chunk in enumerate(en_chunks):
            if not chunk.strip():
                continue

            # 按字符数比例分配时长
            chunk_ratio = len(chunk) / total_en_chars
            chunk_duration = v_duration * chunk_ratio

            # TTS测试实际时长
            temp_path = os.path.join(tempfile.gettempdir(), f"tts_sync_{current_en_index:04d}.mp3")
            try:
                from .tts_engine import TTSEngine
                tts = TTSEngine()
                asyncio.run(tts.synthesize_segment(chunk, "en-US-JennyNeural", temp_path))
                actual_duration = tts._get_audio_duration(temp_path)
                # 使用实际TTS时长
                final_duration = actual_duration
            except:
                final_duration = chunk_duration
            finally:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except:
                        pass

            en_segments.append({
                'index': current_en_index,
                'start': current_pos,
                'end': current_pos + final_duration,
                'text': chunk
            })

            # 确保下一段从当前段的end开始，避免重叠
            current_pos = current_pos + final_duration
            current_en_index += 1

    # 步骤5: 保存英文SRT
    if progress_callback:
        progress_callback(95, 100, "保存英文字幕...")

    if log_callback:
        log_callback("步骤5: 保存英文字幕...")

    output_path = translator_engine._save_translated_srt(srt_path, en_segments, target_lang)

    # 清理音频文件
    try:
        os.remove(audio_path)
    except:
        pass

    if progress_callback:
        progress_callback(100, 100, "完成")

    if log_callback:
        log_callback("=" * 50)
        log_callback(f"✓ 翻译完成")
        log_callback(f"  中文段数: {len(cn_segments)}")
        log_callback(f"  英文段数: {len(en_segments)}")
        log_callback(f"  输出文件: {output_path}")
        log_callback("=" * 50)

    return output_path


translator_engine = TranslatorEngine()


def translate_srt_strict_netflix(srt_path: str, target_lang: str = "en",
                                 progress_callback=None, log_callback=None) -> str:
    """
    严格遵循Netflix+EBU规范的字幕翻译

    核心规则：
    1. 一条中文SRT = 一条英文SRT，共用完全一致的时间轴
    2. 禁止拆分、合并任何时间码
    3. 中文单行≤16字，英文单行≤42字符
    4. 引号括号内文本整体不可拆分
    5. 3字以内零散短句就近合并
    6. 英文仅在连词/介词处换行，禁止单词中间断行

    Args:
        srt_path: 中文字幕文件路径
        target_lang: 目标语言
        progress_callback: 进度回调
        log_callback: 日志回调

    Returns:
        英文SRT文件路径
    """
    if log_callback:
        log_callback("=" * 60)
        log_callback("Netflix+EBU 严格规范翻译模式")
        log_callback("=" * 60)

    # 步骤1: 加载中文SRT
    if progress_callback:
        progress_callback(5, 100, "加载SRT...")

    if log_callback:
        log_callback("步骤1: 加载SRT文件")

    cn_segments = translator_engine.load_srt(srt_path)
    if log_callback:
        log_callback(f"  加载了 {len(cn_segments)} 段中文")

    # 步骤2: 严格1:1翻译
    if progress_callback:
        progress_callback(10, 100, "翻译中...")

    if log_callback:
        log_callback("步骤2: 严格1:1翻译（锁定时间轴）")

    en_segments = []

    for i, seg in enumerate(cn_segments):
        if progress_callback:
            progress = 10 + int((i / len(cn_segments)) * 80)
            progress_callback(progress, 100, f"翻译 {i+1}/{len(cn_segments)}")

        cn_text = seg['text'].strip()
        cn_start = seg['start']
        cn_end = seg['end']

        if not cn_text:
            # 空字幕保留时间轴
            en_segments.append({
                'index': i + 1,
                'start': cn_start,
                'end': cn_end,
                'text': ''
            })
            continue

        # 计算允许的最大字符数（TTS配音目标：15字符/秒）
        cn_duration = cn_end - cn_start
        max_chars = max(20, int(cn_duration * 15))  # 至少20字符，最多按比例

        # 使用当前设置的大模型严格约束翻译；失败时先自动重试，再回退备用翻译
        try:
            en_text = translate_with_minimax_strict(
                cn_text,
                max_chars=max_chars,
                log_callback=log_callback
            )
        except Exception as e:
            if log_callback:
                log_callback(f"  {get_translation_model()} 失败，改用Google翻译: {str(e)[:80]}")
            try:
                en_text = translate_with_google_timeout(cn_text, timeout=10)
                en_text = strip_reasoning_artifacts(en_text)
                en_text = truncate_to_max_chars(en_text, max_chars)
                if log_callback:
                    log_callback(f"    Google翻译成功: {en_text[:30]}...")
            except Exception as fallback_error:
                if log_callback:
                    log_callback(f"    Google翻译也失败，保留原中文并继续下一段: {str(fallback_error)[:80]}")
                en_text = cn_text

        # 处理英文内部换行（≤42字符/行，最多2行）
        en_text_formatted = format_english_subtitle(en_text)

        en_segments.append({
            'index': i + 1,
            'start': cn_start,
            'end': cn_end,
            'text': en_text_formatted
        })

        if log_callback:
            log_callback(f" 段{i+1}: {cn_text[:15]}... -> {en_text_formatted[:30]}...")

    # 步骤3: 保存英文SRT
    if progress_callback:
        progress_callback(95, 100, "保存SRT...")

    if log_callback:
        log_callback("步骤3: 保存英文SRT")

    output_path = translator_engine._save_translated_srt(srt_path, en_segments, target_lang)

    if progress_callback:
        progress_callback(100, 100, "完成")

    if log_callback:
        log_callback("=" * 60)
        log_callback(f"完成: {len(en_segments)}段英文（与中文1:1对应）")
        log_callback(f"输出: {output_path}")
        log_callback("=" * 60)

    return output_path


def translate_with_minimax_strict(text: str, max_chars: int = 42, log_callback=None) -> str:
    """
    使用 MiniMax LLM 进行严格约束翻译（Netflix+EBU规范）

    Args:
        text: 中文原文
        max_chars: 最大字符数限制（默认42字符，符合Netflix单行限制）
        log_callback: 日志回调

    Returns:
        翻译后的英文（已压缩，符合时长要求）
    """
    system_prompt = f"""You are a professional subtitle translator. CRITICAL: Shorten aggressively!

TRANSLATION RULES (MUST follow in order):
1. EXTRACT TRUNK: Keep only Subject + Verb + Object. DELETE all fillers, modifiers, preambles
2. SHORTEN: Use shortest natural English. Every word must earn its place
3. COLLOQUIAL: Convert to short conversational sentences, NOT书面 language
4. SIMPLIFY: Long clauses → noun phrases/prepositional phrases
5. OMIT: spoken fillers (啊, 呢, 嘛,吧, 哦), repeated ideas, hedging phrases
6. KEEP: facts, names, numbers, technical terms

FORBIDDEN:
- Long explanations or compound sentences
- Unnecessary adjectives or adverbs
- First person pronouns unless essential (I, we usually can be omitted)
- Sentence starters like "Regarding this", "Concerning that", "As for"
- Alternative translations, character counts, comments, checks, or analysis
- Quotation marks around the answer

MAXIMUM: ≤ {max_chars} characters per line

EXAMPLES - Note the dramatic shortening:
Chinese: "我很抱歉，但是这种事情我们也没有办法控制。"
Good: "Sorry, can't control this."

Chinese: "那个时候我真的觉得特别的烦躁和郁闷。"
Good: "Really annoyed then."

Chinese: "关于这个问题的解决方案我们需要进一步的讨论。"
Good: "Need further discussion."

Chinese: "现在让我们来学习电气制图认证课程。"
Good: "Learn electrical drafting."

Chinese: "这个是我们电力系统图的组成部分。"
Good: "Part of power system diagram."

Chinese: "这些符号是由国家标准进行标准化的。"
Good: "Standardized by national standard."

OUTPUT: ONLY one final English subtitle line. No explanations, no notes, no alternatives, no character counts, no reasoning, no <think> tags.
"""

    user_prompt = f"""Translate this Chinese subtitle to English.
CRITICAL: Must be ≤ {max_chars} characters. Return only the final subtitle text. Do not add alternatives, comments, quotes, or character counts.

Chinese: {text}
English:"""

    # 检查是否使用Google翻译作为备用
    model_key = get_translation_model()
    if model_key == "Google翻译(备用)":
        # 回退到Google翻译
        try:
            translator = GoogleTranslator(source='zh-CN', target='en')
            result = translator.translate(text)
            if log_callback:
                log_callback(f"    Google: {text[:15]}... -> {result[:25]}...")
            return result
        except Exception as e:
            if log_callback:
                log_callback(f"    Google翻译失败: {str(e)}")
            raise

    # 获取MiniMax模型名
    minimax_model = TRANSLATION_MODELS.get(model_key, "abab6.5s-chat")

    payload = {
        "model": minimax_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 200
    }

    try:
        req = urllib.request.Request(
            f"{MINIMAX_BASE_URL}/chat/completions",
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {MINIMAX_API_KEY}'
            },
            method='POST'
        )

        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            translated = strip_reasoning_artifacts(result['choices'][0]['message']['content'])

            # 确保不超过最大字符限制
            translated = truncate_to_max_chars(translated, max_chars)

            # 如果翻译结果中包含中文字符，或仍像推理内容，则继续让同一模型重译这一条
            retry_count = 0
            max_ai_retries = 8
            while (has_chinese_residue(translated) or looks_like_reasoning(translated)) and retry_count < max_ai_retries:
                retry_count += 1
                if log_callback:
                    if has_chinese_residue(translated):
                        log_callback(f"    检测到中文残留，重新翻译第{retry_count}/{max_ai_retries}次...")
                    else:
                        log_callback(f"    检测到推理内容，重新翻译第{retry_count}/{max_ai_retries}次...")

                retry_payload = {
                    "model": minimax_model,
                    "messages": [
                        {"role": "system", "content": system_prompt + "\n\nCRITICAL FAILURE RECOVERY: The previous output was invalid because it included reasoning or Chinese residue. Translate again from scratch. Return ONLY one short English subtitle. No labels. No quotes. No reasoning. No <think>. No Chinese."},
                        {"role": "user", "content": f"Chinese subtitle:\n{text}\n\nReturn only the English subtitle:"}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 200
                }

                req2 = urllib.request.Request(
                    f"{MINIMAX_BASE_URL}/chat/completions",
                    data=json.dumps(retry_payload).encode('utf-8'),
                    headers={
                        'Content-Type': 'application/json',
                        'Authorization': f'Bearer {MINIMAX_API_KEY}'
                    },
                    method='POST'
                )

                with urllib.request.urlopen(req2, timeout=30) as response2:
                    result2 = json.loads(response2.read().decode('utf-8'))
                    translated = strip_reasoning_artifacts(result2['choices'][0]['message']['content'])
                    translated = truncate_to_max_chars(translated, max_chars)

            if has_chinese_residue(translated) or looks_like_reasoning(translated):
                raise Exception(f"AI连续{max_ai_retries + 1}次返回推理内容或中文残留，未得到有效英文翻译")

            if log_callback:
                if retry_count > 0:
                    log_callback(f"    最终: {translated[:30]}...")
                log_callback(f"    {model_key}: {text[:20]}... -> {translated[:30]}...")

            return translated

    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else ''
        if log_callback:
            log_callback(f"    {model_key} HTTP {e.code}: {error_body[:200]}")
        raise Exception(f"{model_key} HTTP {e.code}: {error_body[:200]}")
    except Exception as e:
        if log_callback:
            log_callback(f"    {model_key} error: {str(e)}")
        raise


def truncate_to_max_chars(text: str, max_chars: int) -> str:
    """
    将文本截断到最大字符数（在单词边界处截断）

    Args:
        text: 原始文本
        max_chars: 最大字符数

    Returns:
        截断后的文本
    """
    if not text or len(text) <= max_chars:
        return text

    # 在空格处截断
    truncated = text[:max_chars]
    last_space = truncated.rfind(' ')

    if last_space > max_chars * 0.6:
        return truncated[:last_space].strip()

    # 如果找不到合适的空格，直接截断
    return truncated.strip() + '...'


def format_english_subtitle(text: str) -> str:
    """
    按讯飞+Netflix规范格式化英文字幕

    规则：
    1. 单行≤42个ASCII字符
    2. 单条字幕最多2行
    3. 超长译文只在连词/介词后换行
    4. 禁止单词中间劈断
    5. 一行能显示完就不换行

    连词：and, or, but, yet, so, because, if, when, while, although
    介词：in, on, at, to, for, with, by, from, about, as, into, through, during, before, after

    Args:
        text: 原始英文文本

    Returns:
        格式化后的英文（保留换行符\n表示实际换行）
    """
    if not text:
        return text

    text = text.strip()

    # ≤42字符，不换行
    if len(text) <= 42:
        return text

    # 收集所有可换行的连词/介词位置
    break_points = []

    # 匹配连词和介词（前面有空格）
    for pattern in [r'\b(and|or|but|yet|so|because|if|when|while|although)\b',
                   r'\b(in|on|at|to|for|with|by|from|about|as|into|through|during|before|after)\b']:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            pos = match.start()
            # 换行点必须在文本中间区域（不能太前不能太后）
            if 15 <= pos <= len(text) - 10:
                break_points.append(pos)

    if break_points:
        # 找最佳换行点：优先靠近42字符的位置
        best_point = min(break_points, key=lambda x: abs(x - 42))
        line1 = text[:best_point].strip()
        line2 = text[best_point:].strip()

        if len(line1) <= 42 and len(line2) <= 42 and len(line2) > 0:
            return f"{line1}\n{line2}"

    # 如果没有合适的连词/介词换行点，返回未换行的原始文本
    #（由外层truncate处理）
    return text



