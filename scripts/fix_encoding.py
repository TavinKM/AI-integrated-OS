#!/usr/bin/env python3
"""
Fix encoding issues in GraphRAG input files.

Converts non-UTF-8 files (like ISO-8859-1) to UTF-8 encoding
so GraphRAG can process them without errors.
"""

import os
from pathlib import Path
import argparse


def fix_file_encoding(filepath: Path, encoding: str = None) -> bool:
    """
    Convert a file to UTF-8 encoding.
    
    Args:
        filepath: Path to the file
        encoding: Specific encoding to try (if None, tries common encodings)
        
    Returns:
        True if conversion was successful, False otherwise
    """
    try:
        # First, try to read as UTF-8 to see if it's already correct
        with open(filepath, 'r', encoding='utf-8') as f:
            f.read()
        return False  # Already UTF-8, no conversion needed
    except UnicodeDecodeError:
        pass  # File needs conversion
    
    # Try to convert from the specified encoding or common encodings
    encodings_to_try = [encoding] if encoding else [
        'iso-8859-1', 'latin-1', 'cp1252', 'windows-1252', 
        'mac-roman', 'cp437'
    ]
    
    for enc in encodings_to_try:
        if not enc:
            continue
        try:
            with open(filepath, 'r', encoding=enc) as f:
                content = f.read()
            
            # Write back as UTF-8
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            
            print(f"Converted {filepath.name} from {enc} to UTF-8")
            return True
        except (UnicodeDecodeError, LookupError):
            continue
        except Exception as e:
            print(f"Error converting {filepath.name}: {e}")
            return False
    
    print(f" Could not determine encoding for {filepath.name}")
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Fix encoding issues in GraphRAG input files"
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("graphrag/input"),
        help="Directory containing input files (default: graphrag/input)"
    )
    parser.add_argument(
        "--encoding",
        type=str,
        default=None,
        help="Specific encoding to convert from (if not specified, tries common encodings)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check files but don't convert them"
    )
    
    args = parser.parse_args()
    
    if not args.input_dir.exists():
        print(f"Input directory not found: {args.input_dir}")
        return 1
    
    txt_files = list(args.input_dir.glob("*.txt"))
    
    if not txt_files:
        print(f"No .txt files found in {args.input_dir}")
        return 0
    
    print(f"Checking {len(txt_files)} text files for encoding issues...\n")
    
    converted = 0
    already_utf8 = 0
    failed = 0
    
    for filepath in sorted(txt_files):
        try:
            # Check if file is already UTF-8
            with open(filepath, 'r', encoding='utf-8') as f:
                f.read()
            already_utf8 += 1
            continue
        except UnicodeDecodeError:
            pass  # File needs conversion
        
        if args.dry_run:
            print(f"{filepath.name} needs conversion (not UTF-8)")
            failed += 1
        else:
            if fix_file_encoding(filepath, args.encoding):
                converted += 1
            else:
                failed += 1
    
    print(f"\n{'=' * 60}")
    print(f"Summary:")
    print(f" Already UTF-8: {already_utf8}")
    if not args.dry_run:
        print(f" Converted: {converted}")
    if failed > 0:
        print(f" Failed/Needs attention: {failed}")
    print(f"{'=' * 60}")
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit(main())



