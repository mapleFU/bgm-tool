import argparse
import json
import sys
import os
import requests

class LLMBackend:
    def __init__(self, api_key, model, base_url=None):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    def generate(self, prompt):
        raise NotImplementedError("Subclasses must implement generate()")

class DeepSeekBackend(LLMBackend):
    def __init__(self, api_key, model="deepseek-chat", base_url="https://api.deepseek.com"):
        super().__init__(api_key, model, base_url)

    def generate(self, prompt):
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        data = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant that analyzes Bangumi anime reviews."},
                {"role": "user", "content": prompt}
            ],
            "stream": False
        }
        try:
            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content']
        except Exception as e:
            return f"Error calling DeepSeek API: {e}"

class OpenAICompatibleBackend(LLMBackend):
    def __init__(self, api_key, model, base_url):
        super().__init__(api_key, model, base_url)

    def generate(self, prompt):
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        data = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant that analyzes Bangumi anime reviews."},
                {"role": "user", "content": prompt}
            ],
            "stream": False
        }
        try:
            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content']
        except Exception as e:
            return f"Error calling API: {e}"

ANALYSIS_TEMPLATE = """
请分析以下关于 Bangumi 条目 "{title}" (ID: {subject_id}) 的评论数据。
条目总评分: {score} (评分人数: {count})

评论内容如下:
{comments_text}

--- 评论结束 ---

请根据以上评论，按照以下结构输出一份详细的分析报告（请使用中文回答）：

### 1. 好评分析 (Positive Review Analysis)
- **好评比例预估**: (例如：约 70%)
- **主要好评点**: 
  - (请列出用户普遍赞赏的方面，如剧情、作画、音乐、人设等)
  - (引用 1-2 个具体的短语或关键词)

### 2. 差评分析 (Negative Review Analysis)
- **差评比例预估**: (例如：约 20%)
- **主要批评点**:
  - (请列出用户普遍不满的方面，如烂尾、崩坏、剧情不合理等)
  - (引用 1-2 个具体的短语或关键词)

### 3. 精选深度评价 (Selected In-Depth Reviews)
请挑选 2-3 条内容详实、观点独特或具有代表性的评论。
- **用户**: {user_placeholder} (评分: {rating_placeholder})
  - **核心观点**: (简要总结该用户的核心观点)
  - **原文摘录**: (摘录一句最能代表其观点的原话)

### 4. 总体总结观点 (Overall Summary)
- 请综合所有评论，用一段话概括该作品在观众心中的整体印象。
- 分析观众的情绪倾向（如：遗憾、惊喜、愤怒、平淡等）。
- 给出该作品适合的受众群体建议（如果有）。

请确保输出格式清晰，使用 Markdown 格式。
"""

def format_comments_for_llm(data):
    """
    Format the JSON data into a structured prompt for the LLM using the template.
    """
    subject_id = data.get("subject_id", "Unknown")
    title = data.get("title", "Unknown Title")
    rating_info = data.get("rating", {})
    score = "N/A"
    count = "N/A"
    
    if isinstance(rating_info, dict):
        score = rating_info.get("score", "N/A")
        # Handle 'count' which can be an int or a dict of distribution
        count_val = rating_info.get("total", "N/A") 
        if count_val == "N/A":
             count_val = rating_info.get("count", "N/A")
        if isinstance(count_val, dict):
             # Sum up values if it's a distribution dict
             try:
                 count = sum(int(v) for v in count_val.values())
             except:
                 count = "N/A"
        else:
             count = count_val

    comments = data.get("comments", [])
    
    comments_text = ""
    for i, comment in enumerate(comments, 1):
        user = comment.get("user", "Unknown")
        rating = comment.get("rating", "N/A")
        date = comment.get("date", "Unknown Date")
        status = comment.get("status", "")
        content = comment.get("content", "").strip()
        
        comments_text += f"{i}. [User: {user}, Rating: {rating}, Date: {date}, Status: {status}]\n"
        comments_text += f"   Content: {content}\n\n"
        
    prompt = ANALYSIS_TEMPLATE.format(
        title=title,
        subject_id=subject_id,
        score=score,
        count=count,
        comments_text=comments_text,
        user_placeholder="{user}",
        rating_placeholder="{rating}"
    )
    
    return prompt

def main():
    parser = argparse.ArgumentParser(description="Analyze Bangumi comments using an LLM.")
    parser.add_argument("input_file", nargs="?", help="Path to JSON file containing comments (reads from stdin if omitted)")
    parser.add_argument("--api-key", help="LLM API Key")
    parser.add_argument("--provider", default="deepseek", choices=["deepseek", "stepfun", "openai-compatible"], help="LLM Provider")
    parser.add_argument("--base-url", help="Custom API Base URL (required for openai-compatible)")
    parser.add_argument("--model", default="deepseek-chat", help="Model name")

    args = parser.parse_args()

    # Get API Key from args or env
    api_key = args.api_key or os.environ.get("LLM_API_KEY")
    if not api_key:
        print("Error: API Key is required. Provide it via --api-key or LLM_API_KEY environment variable.", file=sys.stderr)
        sys.exit(1)

    # Read input data
    if args.input_file:
        try:
            with open(args.input_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"Error reading input file: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # Read from stdin
        if sys.stdin.isatty():
            print("Error: No input file provided and stdin is empty.", file=sys.stderr)
            parser.print_help()
            sys.exit(1)
        try:
            data = json.load(sys.stdin)
        except Exception as e:
            print(f"Error reading from stdin: {e}", file=sys.stderr)
            sys.exit(1)

    # Prepare prompt
    prompt = format_comments_for_llm(data)
    
    # Initialize backend
    if args.provider == "deepseek":
        backend = DeepSeekBackend(api_key, args.model)
    elif args.provider == "stepfun":
        base_url = args.base_url or "https://api.stepfun.com/v1"
        backend = OpenAICompatibleBackend(api_key, args.model, base_url)
    elif args.provider == "openai-compatible":
        if not args.base_url:
             print("Error: --base-url is required for openai-compatible provider.", file=sys.stderr)
             sys.exit(1)
        backend = OpenAICompatibleBackend(api_key, args.model, args.base_url)
    else:
        print(f"Error: Unknown provider {args.provider}", file=sys.stderr)
        sys.exit(1)

    # Generate analysis
    print("Generating analysis...", file=sys.stderr)
    result = backend.generate(prompt)
    print(result)

if __name__ == "__main__":
    main()
