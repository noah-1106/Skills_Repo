#!/usr/bin/env python3
"""
Style Fingerprint Lite - Chinese Writing Style Analyzer (No jieba dependency)
Basic version using regex and character-level analysis.
"""

import os
import re
import json
import argparse
from typing import Dict, List, Optional
from pathlib import Path

# Get skill directory
SKILL_DIR = Path(__file__).parent.resolve()
FINGERPRINTS_DIR = SKILL_DIR / "fingerprints"
FINGERPRINTS_DIR.mkdir(exist_ok=True)

# Common Chinese function words (stopwords)
STOPWORDS = set([
    '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个',
    '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好',
    '自己', '这', '那', '们', '来', '个', '吗', '吧', '啊', '呢', '哦', '嗯', '为',
    '之', '与', '及', '等', '或', '但', '而', '因', '于', '以', '被', '把', '让',
    '给', '向', '往', '从', '到', '在', '当', '比', '跟', '同', '对', '关于', '根据',
    '可以', '这个', '那个', '什么', '怎么', '为什么', '如果', '因为', '所以', '但是'
])


class SimpleChineseTokenizer:
    """Simple Chinese tokenizer without jieba dependency."""
    
    @staticmethod
    def cut(text: str) -> List[str]:
        """Simple word segmentation using regex patterns."""
        # Pattern for Chinese words (2-4 characters)
        # Matches common word patterns
        words = []
        
        # Extract potential words (2-4 character sequences)
        # This is a simplified approach - looks for character sequences
        i = 0
        while i < len(text):
            if '\u4e00' <= text[i] <= '\u9fff':  # Chinese character
                # Try to form words (2-4 chars)
                for length in [4, 3, 2]:
                    if i + length <= len(text):
                        candidate = text[i:i+length]
                        if all('\u4e00' <= c <= '\u9fff' for c in candidate):
                            words.append(candidate)
                            i += length
                            break
                else:
                    words.append(text[i])
                    i += 1
            else:
                i += 1
        
        return words


class StyleFingerprint:
    """Chinese writing style analyzer (lite version)."""
    
    def __init__(self):
        self.stopwords = STOPWORDS
        self.tokenizer = SimpleChineseTokenizer()
    
    def analyze(self, text: str) -> Dict:
        """Analyze text and return style fingerprint."""
        
        text = text.strip()
        if not text:
            raise ValueError("Empty text provided")
        
        # 1. Basic syntax statistics
        sentences = re.split(r'[。！？\n]+', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 0]
        
        sentence_lengths = [len(s) for s in sentences]
        avg_len = sum(sentence_lengths) / len(sentence_lengths) if sentences else 0
        
        # Comma density
        comma_count = text.count('，')
        comma_density = comma_count / len(sentences) if sentences else 0
        
        # 2. Lexical fingerprint (simplified)
        words = self.tokenizer.cut(text)
        content_words = [w for w in words if len(w) >= 2 and w not in self.stopwords]
        
        # Count word frequencies
        word_counts = {}
        for w in content_words:
            word_counts[w] = word_counts.get(w, 0) + 1
        
        # Sort by frequency
        word_freq = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:30]
        
        # 3. Syntax patterns
        patterns = {
            "rhetorical_question": len(re.findall(r'[难道岂怎么].*？[呢吗]', text)),
            "passive_voice": len(re.findall(r'被|由|受到', text)),
            "ellipsis_subject": self._detect_ellipsis(sentences),
            "long_attributive": len(re.findall(r'的.*的', text))
        }
        
        # 4. Transition words
        transitions = {
            "contrast": len(re.findall(r'但是|然而|不过|只是|却', text)),
            "causal": len(re.findall(r'所以|因此|于是|因为|由于', text)),
            "progressive": len(re.findall(r'而且|甚至|况且|并且', text)),
            "concessive": len(re.findall(r'虽然|尽管|即使|固然', text))
        }
        
        # 5. Rhetorical features
        metaphors = self._detect_metaphor(text)
        sensory = self._sensory_analysis(text)
        
        # 6. Generate guide
        guide = self._generate_guide(avg_len, patterns, word_freq, sensory)
        
        return {
            "basic_stats": {
                "total_chars": len(text),
                "sentence_count": len(sentences),
                "avg_sentence_length": round(avg_len, 1),
                "comma_density": round(comma_density, 2),
                "rhythm": self._judge_rhythm(avg_len, comma_density)
            },
            "syntax_preference": {
                "sentence_pattern": self._judge_sentence_pattern(avg_len),
                "patterns": patterns
            },
            "lexicon_fingerprint": {
                "top_words": [w[0] for w in word_freq[:15]],
                "top_words_with_freq": word_freq[:10],
                "word_diversity": round(len(set(content_words)) / len(content_words), 3) if content_words else 0,
                "total_words": len(words),
                "content_words": len(content_words)
            },
            "logic_flow": transitions,
            "rhetoric": {
                "metaphor_count": len(metaphors),
                "metaphor_examples": metaphors[:5],
                "sensory_analysis": sensory
            },
            "writing_guide": guide
        }
    
    def _detect_ellipsis(self, sentences: List[str]) -> int:
        """Detect subject ellipsis."""
        count = 0
        ellipsis_patterns = r'^[是|有|让|使|感到|看着|听着|想起|终于|其实|原来|大概|也许|可能|应该]'
        for sent in sentences[1:]:
            if re.match(ellipsis_patterns, sent):
                count += 1
        return count
    
    def _detect_metaphor(self, text: str) -> List[str]:
        """Simple metaphor detection."""
        patterns = [
            r'[\u4e00-\u9fa5]{2,4}(?:像|仿佛|如同|似|像是|犹如|好比)[\u4e00-\u9fa5]{2,8}',
            r'[\u4e00-\u9fa5]{2,4}(?:是|成为|变成)[\u4e00-\u9fa5]{2,6}(?:的|一样)'
        ]
        metaphors = []
        for pattern in patterns:
            matches = re.findall(pattern, text)
            metaphors.extend(matches)
        return metaphors[:5]
    
    def _sensory_analysis(self, text: str) -> Dict:
        """Analyze sensory description."""
        visual = len(re.findall(r'看|见|颜色|光|影|色|形状|样子|画面|视觉', text))
        auditory = len(re.findall(r'听|声|音|响|静|噪音|音乐|说话|听觉', text))
        tactile = len(re.findall(r'摸|冷|热|痛|软|硬|温度|触觉|质感', text))
        olfactory = len(re.findall(r'闻|香|臭|味|气味|嗅觉', text))
        gustatory = len(re.findall(r'吃|喝|味道|甜|苦|酸|辣|咸|味觉', text))
        
        total = visual + auditory + tactile + olfactory + gustatory
        
        if total == 0:
            dominant = "abstract"
            dominant_cn = "抽象叙述"
        else:
            senses = [
                ("visual", visual, "视觉描写"),
                ("auditory", auditory, "听觉描写"),
                ("tactile", tactile, "触觉描写"),
                ("olfactory", olfactory, "嗅觉描写"),
                ("gustatory", gustatory, "味觉描写")
            ]
            dominant, _, dominant_cn = max(senses, key=lambda x: x[1])
        
        return {
            "visual": visual,
            "auditory": auditory,
            "tactile": tactile,
            "olfactory": olfactory,
            "gustatory": gustatory,
            "total_sensory": total,
            "dominant": dominant,
            "dominant_cn": dominant_cn,
            "sensory_ratio": round(total / len(text) * 100, 2) if text else 0
        }
    
    def _judge_rhythm(self, avg_len: float, comma_density: float) -> str:
        """Judge text rhythm."""
        if avg_len < 15 and comma_density < 0.5:
            return "短促有力"
        elif avg_len > 30 and comma_density > 1.5:
            return "绵长舒缓"
        elif comma_density > 1.0:
            return "节奏舒缓"
        elif comma_density < 0.5:
            return "节奏紧凑"
        else:
            return "节奏自然"
    
    def _judge_sentence_pattern(self, avg_len: float) -> str:
        """Judge sentence pattern."""
        if avg_len < 18:
            return "短句为主"
        elif avg_len > 28:
            return "长句为主"
        else:
            return "长短交错"
    
    def _generate_guide(self, avg_len: float, patterns: Dict, word_freq: List, sensory: Dict) -> List[str]:
        """Generate writing guide."""
        guides = []
        
        if avg_len < 18:
            guides.append("【句式】多用短句，营造断裂感和节奏感，适合强调和冲击")
            guides.append("【禁忌】避免连续使用超过25字的长句，会破坏短句节奏")
        elif avg_len > 28:
            guides.append("【句式】长句缠绕，适合复杂逻辑铺陈和情绪递进")
            guides.append("【禁忌】避免连续短句，会破坏绵长感")
        else:
            guides.append("【句式】长短句交错，张弛有度，适合大多数场景")
        
        if patterns["ellipsis_subject"] > 2:
            guides.append("【人称】习惯省略主语，通过动作和状态暗示主体，增加沉浸感")
        
        if word_freq:
            top_word = word_freq[0][0]
            guides.append(f"【词汇标记】高频使用'{top_word}'，可作为个人风格印记保留")
        
        if sensory["dominant"] != "abstract":
            guides.append(f"【感官】偏好{sensory['dominant_cn']}，写作时可强化此维度")
        
        if patterns["rhetorical_question"] > 0:
            guides.append("【修辞】善用反问句增强语气和互动感")
        
        if patterns["long_attributive"] > 2:
            guides.append("【修辞】习惯使用长定语堆叠，形成独特的修饰风格")
        
        return guides


class FingerprintStorage:
    """Manage fingerprint persistence."""
    
    @staticmethod
    def save(name: str, fingerprint: Dict, source_text: str = ""):
        """Save fingerprint to JSON."""
        filepath = FINGERPRINTS_DIR / f"{name}.json"
        data = {
            "name": name,
            "fingerprint": fingerprint,
            "source_text_sample": source_text[:500] if source_text else "",
            "created_at": str(__import__('datetime').datetime.now())
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✓ Saved fingerprint: {filepath}")
    
    @staticmethod
    def load(name: str) -> Optional[Dict]:
        """Load fingerprint."""
        filepath = FINGERPRINTS_DIR / f"{name}.json"
        if not filepath.exists():
            return None
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    @staticmethod
    def list_all() -> List[str]:
        """List all fingerprints."""
        files = FINGERPRINTS_DIR.glob("*.json")
        return sorted([f.stem for f in files])
    
    @staticmethod
    def delete(name: str) -> bool:
        """Delete fingerprint."""
        filepath = FINGERPRINTS_DIR / f"{name}.json"
        if filepath.exists():
            filepath.unlink()
            return True
        return False


def format_output(fingerprint: Dict, name: str) -> str:
    """Format for display."""
    basic = fingerprint["basic_stats"]
    lexicon = fingerprint["lexicon_fingerprint"]
    rhetoric = fingerprint["rhetoric"]
    
    output = f"""
╔══════════════════════════════════════════════════════════╗
║           【风格指纹分析报告】{name[:20]:^20}           ║
╚══════════════════════════════════════════════════════════╝

📊 基础指标
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• 总字数：{basic['total_chars']} 字
• 句子数：{basic['sentence_count']} 句
• 平均句长：{basic['avg_sentence_length']} 字（{fingerprint['syntax_preference']['sentence_pattern']}）
• 逗号密度：{basic['comma_density']}
• 整体节奏：{basic['rhythm']}

📝 词汇指纹
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• 词汇丰富度：{lexicon['word_diversity']}
• 高频词汇：{', '.join(lexicon['top_words'][:8])}

🎯 核心写作指南
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    for guide in fingerprint["writing_guide"]:
        output += f"• {guide}\n"
    
    output += f"""
🔍 修辞特征
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• 隐喻使用：{rhetoric['metaphor_count']} 处
• 主导感官：{rhetoric['sensory_analysis']['dominant_cn']}
• 感官描写占比：{rhetoric['sensory_analysis']['sensory_ratio']}%

💡 给写作 Agent 的指令
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
请严格遵循上述"核心写作指南"，保持{basic['rhythm']}的节奏，
使用标记词汇（{lexicon['top_words'][0] if lexicon['top_words'] else '无'}等），
维持{rhetoric['sensory_analysis']['dominant_cn']}的习惯。
"""
    return output


def export_style_guide(fingerprint: Dict, name: str) -> str:
    """Export compact style guide."""
    basic = fingerprint["basic_stats"]
    lexicon = fingerprint["lexicon_fingerprint"]
    rhetoric = fingerprint["rhetoric"]
    
    guide = f"""# 写作风格指南：{name}

## 句式要求
- 平均句长：{basic['avg_sentence_length']} 字（{fingerprint['syntax_preference']['sentence_pattern']}）
- 整体节奏：{basic['rhythm']}

## 核心规则
"""
    for g in fingerprint["writing_guide"]:
        guide += f"- {g}\n"
    
    guide += f"""
## 词汇偏好
- 高频词：{', '.join(lexicon['top_words'][:5])}
- 词汇丰富度：{lexicon['word_diversity']}

## 修辞风格
- 主导感官：{rhetoric['sensory_analysis']['dominant_cn']}
- 隐喻使用：{'频繁' if rhetoric['metaphor_count'] > 2 else '适度' if rhetoric['metaphor_count'] > 0 else '较少'}

## 写作指令
以{basic['rhythm']}的节奏写作，保持{fingerprint['syntax_preference']['sentence_pattern']}，
适当使用高频词汇作为风格印记，强化{rhetoric['sensory_analysis']['dominant_cn']}。
"""
    return guide


def main():
    parser = argparse.ArgumentParser(description="Style Fingerprint - Chinese Writing Style Analyzer")
    subparsers = parser.add_subparsers(dest="command")
    
    # Analyze
    analyze_parser = subparsers.add_parser("analyze", help="Analyze and save fingerprint")
    analyze_parser.add_argument("--text", "-t", help="Text to analyze")
    analyze_parser.add_argument("--file", "-f", help="File path")
    analyze_parser.add_argument("--name", "-n", required=True, help="Fingerprint name")
    
    # List
    subparsers.add_parser("list", help="List fingerprints")
    
    # Show
    show_parser = subparsers.add_parser("show", help="Show fingerprint")
    show_parser.add_argument("--name", "-n", required=True)
    
    # Delete
    delete_parser = subparsers.add_parser("delete", help="Delete fingerprint")
    delete_parser.add_argument("--name", "-n", required=True)
    
    # Export
    export_parser = subparsers.add_parser("export", help="Export style guide")
    export_parser.add_argument("--name", "-n", required=True)
    export_parser.add_argument("--output", "-o", help="Output file")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    storage = FingerprintStorage()
    
    if args.command == "analyze":
        if args.file:
            with open(args.file, 'r', encoding='utf-8') as f:
                text = f.read()
        elif args.text:
            text = args.text
        else:
            print("Error: Provide --text or --file")
            return
        
        analyzer = StyleFingerprint()
        fingerprint = analyzer.analyze(text)
        storage.save(args.name, fingerprint, text)
        print(format_output(fingerprint, args.name))
    
    elif args.command == "list":
        fps = storage.list_all()
        if fps:
            print("Saved fingerprints:")
            for fp in fps:
                print(f"  • {fp}")
        else:
            print("No fingerprints saved.")
    
    elif args.command == "show":
        data = storage.load(args.name)
        if data:
            print(format_output(data["fingerprint"], args.name))
        else:
            print(f"Not found: {args.name}")
    
    elif args.command == "delete":
        if storage.delete(args.name):
            print(f"Deleted: {args.name}")
        else:
            print(f"Not found: {args.name}")
    
    elif args.command == "export":
        data = storage.load(args.name)
        if data:
            guide = export_style_guide(data["fingerprint"], args.name)
            if args.output:
                with open(args.output, 'w', encoding='utf-8') as f:
                    f.write(guide)
                print(f"Exported to: {args.output}")
            else:
                print(guide)
        else:
            print(f"Not found: {args.name}")


if __name__ == "__main__":
    main()
