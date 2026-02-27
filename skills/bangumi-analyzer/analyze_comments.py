import argparse
import json
import sys
import os
import requests
import concurrent.futures

class LLMBackend:
    def __init__(self, api_key, model, base_url):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip('/')

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

BATCH_ANALYSIS_TEMPLATE = """
请分析以下关于 Bangumi 条目 "{title}" (ID: {subject_id}) 的一部分评论数据（第 {start_index} 到 {end_index} 条）。

评论内容如下:
{comments_text}

--- 评论结束 ---

请简要总结这批评论的以下信息（请使用中文）：
1. **主要好评点**: 用户满意的方面。
2. **主要批评点**: 用户不满的方面。
3. **精选评论**: 挑选 1-2 条最有代表性或最有深度的评论（保留用户、评分和原始内容）。
4. **情感倾向**: 这批评论的整体情感（正面/负面/混合）。

不需要输出完整的格式化报告，只需要提取关键信息以便后续汇总。
"""

FINAL_SUMMARY_TEMPLATE = """
以下是关于 Bangumi 条目 "{title}" (ID: {subject_id}) 的多批评论分析汇总。
条目总评分: {score} (评分人数: {count})

--- 分析汇总开始 ---
{summaries_text}
--- 分析汇总结束 ---

请根据以上所有批次的分析结果，综合整理成一份最终的详细分析报告（请使用中文回答）：

### 1. 好评分析 (Positive Review Analysis)
- **好评比例预估**: (根据整体情感倾向估算)
- **主要好评点**: 
  - (请列出用户普遍赞赏的方面，如剧情、作画、音乐、人设等)
  - (引用 1-2 个具体的短语或关键词)

### 2. 差评分析 (Negative Review Analysis)
- **差评比例预估**: (根据整体情感倾向估算)
- **主要批评点**:
  - (请列出用户普遍不满的方面，如烂尾、崩坏、剧情不合理等)
  - (引用 1-2 个具体的短语或关键词)

### 3. 精选深度评价 (Selected In-Depth Reviews)
请从汇总信息中提供的精选评论里，挑选所有留下的最优质的评论。
- **用户**: {user_placeholder} (评分: {rating_placeholder})
  - **核心观点**: (简要总结该用户的核心观点)
  - **原文摘录**: (摘录一句最能代表其观点的原话)

### 4. 总体总结观点 (Overall Summary)
- 请综合所有评论，用一段话概括该作品在观众心中的整体印象。
- 分析观众的情绪倾向（如：遗憾、惊喜、愤怒、平淡等）。
- 给出该作品适合的受众群体建议（如果有）。

请确保输出格式清晰，使用 Markdown 格式。
"""

def get_subject_metadata(data):
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
    return subject_id, title, score, count

def format_comments_text(comments, start_index=1):
    comments_text = ""
    for i, comment in enumerate(comments, start_index):
        user = comment.get("user", "Unknown")
        rating = comment.get("rating", "N/A")
        date = comment.get("date", "Unknown Date")
        content = comment.get("content", "").strip().replace('\n', ' ') # Flatten content
        
        # Compact format:
        # 1. [Rating:8] Content... (User: xxx, Date: yyyy-mm-dd)
        comments_text += f"{i}. [Rating:{rating}] {content} (User: {user}, Date: {date})\n"
    return comments_text

def format_comments_for_llm(data):
    """
    Format the JSON data into a structured prompt for the LLM using the template.
    """
    subject_id, title, score, count = get_subject_metadata(data)
    comments = data.get("comments", [])
    comments_text = format_comments_text(comments)
        
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

def format_batch_prompt(data, comments_batch, start_index):
    subject_id, title, score, count = get_subject_metadata(data)
    comments_text = format_comments_text(comments_batch, start_index)
    
    prompt = BATCH_ANALYSIS_TEMPLATE.format(
        title=title,
        subject_id=subject_id,
        start_index=start_index,
        end_index=start_index + len(comments_batch) - 1,
        comments_text=comments_text
    )
    return prompt

def format_final_summary_prompt(data, batch_summaries):
    subject_id, title, score, count = get_subject_metadata(data)
    
    summaries_text = ""
    for i, summary in enumerate(batch_summaries, 1):
        summaries_text += f"### Batch {i} Analysis:\n{summary}\n\n"
        
    prompt = FINAL_SUMMARY_TEMPLATE.format(
        title=title,
        subject_id=subject_id,
        score=score,
        count=count,
        summaries_text=summaries_text,
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
    parser.add_argument("--batch-size", type=int, default=1000, help="Number of comments per batch for large files (default: 50)")

    args = parser.parse_args()

    # Get API Key from args or env
    api_key = args.api_key or os.environ.get("LLM_API_KEY")
    if not api_key:
        print("Error: API Key is required. Provide it via --api-key or LLM_API_KEY environment variable.", file=sys.stderr)
        sys.exit(1)

    # Read input data
    data = None
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

    # Initialize backend
    base_url = args.base_url
    
    if args.provider == "deepseek":
        if not base_url:
            base_url = "https://api.deepseek.com"
    elif args.provider == "stepfun":
        if not base_url:
            base_url = "https://api.stepfun.com/v1"
    elif args.provider == "openai-compatible":
        if not base_url:
             print("Error: --base-url is required for openai-compatible provider.", file=sys.stderr)
             sys.exit(1)
    else:
        print(f"Error: Unknown provider {args.provider}", file=sys.stderr)
        sys.exit(1)

    backend = LLMBackend(api_key, args.model, base_url)

    # Check comment count and decide mode
    comments = data.get("comments", [])
    total_comments = len(comments)
    
    if total_comments > args.batch_size:
        print(f"Large file detected ({total_comments} comments). Using batch processing mode (Batch size: {args.batch_size})...", file=sys.stderr)
        
        num_batches = (total_comments + args.batch_size - 1) // args.batch_size
        
        def process_batch(idx):
            start_idx = idx * args.batch_size
            end_idx = min((idx + 1) * args.batch_size, total_comments)
            batch_comments = comments[start_idx:end_idx]
            
            print(f"Processing batch {idx+1}/{num_batches} (Comments {start_idx+1}-{end_idx})...", file=sys.stderr)
            
            # Format prompt for this batch
            prompt = format_batch_prompt(data, batch_comments, start_idx + 1)
            
            # Generate summary for this batch
            try:
                return backend.generate(prompt)
            except Exception as e:
                print(f"Error processing batch {idx+1}: {e}", file=sys.stderr)
                return f"Error processing batch {idx+1}"

        # Hardcoded max_workers=3 as requested
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            # We want to maintain order of results for the final summary
            futures = [executor.submit(process_batch, i) for i in range(num_batches)]
            # Wait for all to complete and gather results in order
            batch_summaries = [f.result() for f in futures]
        
        print("Generating final summary...", file=sys.stderr)
        final_prompt = format_final_summary_prompt(data, batch_summaries)
        result = backend.generate(final_prompt)
        print(result)
        
    else:
        # Single shot mode
        print(f"Processing {total_comments} comments...", file=sys.stderr)
        prompt = format_comments_for_llm(data)
        print("Generating analysis...", file=sys.stderr)
        result = backend.generate(prompt)
        print(result)

if __name__ == "__main__":
    main()
