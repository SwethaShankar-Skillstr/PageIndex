import argparse
import os
import json
import re
from pageindex import *
from pageindex.page_index_md import md_to_tree


def add_image_fields(tree):
    if not isinstance(tree, list):
        raise TypeError(f"Expected tree to be a list, got {type(tree).__name__}: {tree!r}")

    def traverse(nodes):
        if not isinstance(nodes, list):
            raise TypeError(f"Expected nodes to be a list, got {type(nodes).__name__}: {nodes!r}")

        for node in nodes:
            if not isinstance(node, dict):
                raise TypeError(f"Expected node to be a dict, got {type(node).__name__}: {node!r}")

            node["image_present"] = False
            node["images"] = []

            child_nodes = node.get("nodes")
            if child_nodes:
                traverse(child_nodes)

    traverse(tree)
    return tree


# -----------------------------
# Filtering helpers
# -----------------------------
BLOCKLIST_TERMS = [
    "manu menon",
    "the painted sky",
    "leo burnett",
    "stay in touch",
    "hope it was informative",
    "what helps people, helps business",
]

COMPANY_NAMES = [
    "rakuten",
    "ey",
    "bosch",
    "the painted sky",
]

GENERIC_BAD_PATTERNS = [
    r"\bthe end\b",
    r"\bstay in touch\b",
    r"\bhope it was informative\b",
    r"\bfeedback\b",
    r"\bcontact us\b",
]

def normalize_text(text):
    if not text:
        return ""
    return str(text).strip().lower()


def contains_blocked_term(text):
    text = normalize_text(text)
    return any(term in text for term in BLOCKLIST_TERMS)


def is_branding_or_closing_node(node):
    title = normalize_text(node.get("title", ""))
    summary = normalize_text(node.get("summary", ""))

    combined = f"{title} {summary}"

    BAD_SIGNALS = [
        "the end",
        "stay in touch",
        "contact",
        "feedback",
        "hope it was informative",
        "quote",
    ]

    return any(signal in combined for signal in BAD_SIGNALS)


def clean_summary_text(text):
    """
    Optional cleanup instead of dropping:
    remove names like Manu Menon / Rakuten from summaries.
    """
    if not text:
        return text

    replacements = [
        (r"\bManu Menon\b", ""),
        (r"\bRakuten\b", ""),
        (r"\bThe Painted Sky\b", ""),
    ]

    cleaned = text
    for pattern, repl in replacements:
        cleaned = re.sub(pattern, repl, cleaned, flags=re.IGNORECASE)

    # Clean extra spaces left behind
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    cleaned = re.sub(r"\s+([,.!?:;])", r"\1", cleaned)

    return cleaned

def remove_company_names(text: str) -> str:
    if not text:
        return text

    cleaned = text

    for company in COMPANY_NAMES:
        pattern = re.compile(rf"\b{re.escape(company)}\b", re.IGNORECASE)
        cleaned = pattern.sub("", cleaned)

    # cleanup spacing
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.!?:;])", r"\1", cleaned)

    return cleaned.strip()


def filter_nodes(nodes):
    cleaned_nodes = []

    for node in nodes:
        if not isinstance(node, dict):
            continue

        node = dict(node)

        # recurse
        if isinstance(node.get("nodes"), list):
            node["nodes"] = filter_nodes(node["nodes"])

        # ✨ sanitize text
        if "title" in node:
            node["title"] = remove_company_names(node["title"])

        if "summary" in node:
            node["summary"] = remove_company_names(node["summary"])

        # ✨ drop useless slides
        if is_branding_or_closing_node(node):
            continue

        cleaned_nodes.append(node)

    return cleaned_nodes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Process PDF or Markdown document and generate structure')
    parser.add_argument('--pdf_path', type=str, help='Path to the PDF file')
    parser.add_argument('--md_path', type=str, help='Path to the Markdown file')

    parser.add_argument('--model', type=str, default='gpt-4o-2024-11-20', help='Model to use')

    parser.add_argument('--toc-check-pages', type=int, default=20,
                        help='Number of pages to check for table of contents (PDF only)')
    parser.add_argument('--max-pages-per-node', type=int, default=10,
                        help='Maximum number of pages per node (PDF only)')
    parser.add_argument('--max-tokens-per-node', type=int, default=20000,
                        help='Maximum number of tokens per node (PDF only)')

    parser.add_argument('--if-add-node-id', type=str, default='yes',
                        help='Whether to add node id to the node')
    parser.add_argument('--if-add-node-summary', type=str, default='yes',
                        help='Whether to add summary to the node')
    parser.add_argument('--if-add-doc-description', type=str, default='no',
                        help='Whether to add doc description to the doc')
    parser.add_argument('--if-add-node-text', type=str, default='no',
                        help='Whether to add text to the node')

    # Markdown specific arguments
    parser.add_argument('--if-thinning', type=str, default='no',
                        help='Whether to apply tree thinning for markdown (markdown only)')
    parser.add_argument('--thinning-threshold', type=int, default=5000,
                        help='Minimum token threshold for thinning (markdown only)')
    parser.add_argument('--summary-token-threshold', type=int, default=200,
                        help='Token threshold for generating summaries (markdown only)')

    parser.add_argument("--output_dir", type=str, default="./results", help="Directory to save structured JSON")
    args = parser.parse_args()

    if os.path.isabs(args.output_dir):
        output_dir = args.output_dir
    else:
        output_dir = os.path.abspath(os.path.join(os.getcwd(), args.output_dir))

    os.makedirs(output_dir, exist_ok=True)

    print(f"[PageIndex] Saving JSON to: {output_dir}")

    if not args.pdf_path and not args.md_path:
        raise ValueError("Either --pdf_path or --md_path must be specified")
    if args.pdf_path and args.md_path:
        raise ValueError("Only one of --pdf_path or --md_path can be specified")

    if args.pdf_path:
        if not args.pdf_path.lower().endswith('.pdf'):
            raise ValueError("PDF file must have .pdf extension")
        if not os.path.isfile(args.pdf_path):
            raise ValueError(f"PDF file not found: {args.pdf_path}")

        opt = config(
            model=args.model,
            toc_check_page_num=args.toc_check_pages,
            max_page_num_each_node=args.max_pages_per_node,
            max_token_num_each_node=args.max_tokens_per_node,
            if_add_node_id=args.if_add_node_id,
            if_add_node_summary=args.if_add_node_summary,
            if_add_doc_description=args.if_add_doc_description,
            if_add_node_text=args.if_add_node_text
        )

        result = page_index_main(args.pdf_path, opt)

        if not isinstance(result, dict) or "structure" not in result:
            raise TypeError(f"Expected page_index_main to return dict with 'structure', got: {type(result).__name__}: {result!r}")

        result["structure"] = add_image_fields(result["structure"])
        result["structure"] = filter_nodes(result["structure"])

        # Optional cleanup on top-level doc description
        if "doc_description" in result and isinstance(result["doc_description"], str):
            result["doc_description"] = clean_summary_text(result["doc_description"])

        print('Parsing done, saving to file...')

        output_dir = os.path.abspath(args.output_dir)
        os.makedirs(output_dir, exist_ok=True)

        pdf_name = os.path.splitext(os.path.basename(args.pdf_path))[0]
        output_file = os.path.join(output_dir, f"{pdf_name}_structure.json")

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        print(f'Tree structure saved to: {output_file}')

    elif args.md_path:
        if not args.md_path.lower().endswith(('.md', '.markdown')):
            raise ValueError("Markdown file must have .md or .markdown extension")
        if not os.path.isfile(args.md_path):
            raise ValueError(f"Markdown file not found: {args.md_path}")

        print('Processing markdown file...')

        import asyncio
        from pageindex.utils import ConfigLoader
        config_loader = ConfigLoader()

        user_opt = {
            'model': args.model,
            'if_add_node_summary': args.if_add_node_summary,
            'if_add_doc_description': args.if_add_doc_description,
            'if_add_node_text': args.if_add_node_text,
            'if_add_node_id': args.if_add_node_id
        }

        opt = config_loader.load(user_opt)

        toc_with_page_number = asyncio.run(md_to_tree(
            md_path=args.md_path,
            if_thinning=args.if_thinning.lower() == 'yes',
            min_token_threshold=args.thinning_threshold,
            if_add_node_summary=opt.if_add_node_summary,
            summary_token_threshold=args.summary_token_threshold,
            model=opt.model,
            if_add_doc_description=opt.if_add_doc_description,
            if_add_node_text=opt.if_add_node_text,
            if_add_node_id=opt.if_add_node_id
        ))

        # Optional: if markdown tree is a list, also clean it
        if isinstance(toc_with_page_number, list):
            toc_with_page_number = add_image_fields(toc_with_page_number)
            toc_with_page_number = filter_nodes(toc_with_page_number)

        print('Parsing done, saving to file...')

        md_name = os.path.splitext(os.path.basename(args.md_path))[0]
        output_dir = './results'
        output_file = f'{output_dir}/{md_name}_structure.json'
        os.makedirs(output_dir, exist_ok=True)

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(toc_with_page_number, f, indent=2, ensure_ascii=False)

        print(f'Tree structure saved to: {output_file}')