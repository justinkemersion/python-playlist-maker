#!/usr/bin/env python3
"""
Improvement Tracking Script for Playlist Maker

This script helps manage and track improvement suggestions for the project.
"""

import os
import sys
from datetime import datetime
from pathlib import Path

def add_improvement(category, description, priority="medium"):
    """Add a new improvement suggestion to the tracking system."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Read current improvements
    improvements_file = Path("QUICK_IMPROVEMENTS.md")
    if improvements_file.exists():
        with open(improvements_file, 'r') as f:
            content = f.read()
    else:
        content = "# Quick Improvement Suggestions\n\n"
    
    # Add new improvement
    new_item = f"- [ ] **{description}** (Added: {timestamp}, Priority: {priority})\n"
    
    # Find the appropriate section or create it
    if f"## {category}" in content:
        # Insert after the category header
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if line.startswith(f"## {category}"):
                # Find the next non-empty line and insert after it
                for j in range(i+1, len(lines)):
                    if lines[j].strip() and not lines[j].startswith('#'):
                        lines.insert(j+1, f"  {new_item}")
                        break
                break
        content = '\n'.join(lines)
    else:
        # Add new category
        content += f"\n## {category}\n\n  {new_item}\n"
    
    # Write back
    with open(improvements_file, 'w') as f:
        f.write(content)
    
    print(f"✅ Added improvement: {description}")
    print(f"📁 Category: {category}")
    print(f"⚡ Priority: {priority}")

def list_improvements():
    """List all current improvements by category."""
    improvements_file = Path("QUICK_IMPROVEMENTS.md")
    if not improvements_file.exists():
        print("❌ No improvements file found. Run with --add to create one.")
        return
    
    with open(improvements_file, 'r') as f:
        content = f.read()
    
    print("📋 Current Improvement Suggestions:")
    print("=" * 50)
    print(content)

def mark_completed(description):
    """Mark an improvement as completed."""
    improvements_file = Path("QUICK_IMPROVEMENTS.md")
    if not improvements_file.exists():
        print("❌ No improvements file found.")
        return
    
    with open(improvements_file, 'r') as f:
        content = f.read()
    
    # Replace [ ] with [x] for matching description
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if description.lower() in line.lower() and '[ ]' in line:
            lines[i] = line.replace('[ ]', '[x]')
            break
    else:
        print(f"❌ Could not find improvement: {description}")
        return
    
    with open(improvements_file, 'w') as f:
        f.write('\n'.join(lines))
    
    print(f"✅ Marked as completed: {description}")

def show_stats():
    """Show statistics about improvements."""
    improvements_file = Path("QUICK_IMPROVEMENTS.md")
    if not improvements_file.exists():
        print("❌ No improvements file found.")
        return
    
    with open(improvements_file, 'r') as f:
        content = f.read()
    
    total = content.count('- [')
    completed = content.count('- [x]')
    pending = content.count('- [ ]')
    
    print("📊 Improvement Statistics:")
    print(f"   Total items: {total}")
    print(f"   Completed: {completed}")
    print(f"   Pending: {pending}")
    print(f"   Progress: {(completed/total*100):.1f}%" if total > 0 else "   Progress: 0%")

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python track_improvements.py --list                    # List all improvements")
        print("  python track_improvements.py --add 'description'       # Add improvement")
        print("  python track_improvements.py --complete 'description'  # Mark as completed")
        print("  python track_improvements.py --stats                   # Show statistics")
        return
    
    command = sys.argv[1]
    
    if command == "--list":
        list_improvements()
    elif command == "--add":
        if len(sys.argv) < 3:
            print("❌ Please provide a description for the improvement.")
            return
        description = sys.argv[2]
        category = input("Category (default: Code Issues): ").strip() or "Code Issues"
        priority = input("Priority (low/medium/high, default: medium): ").strip() or "medium"
        add_improvement(category, description, priority)
    elif command == "--complete":
        if len(sys.argv) < 3:
            print("❌ Please provide a description to mark as completed.")
            return
        description = sys.argv[2]
        mark_completed(description)
    elif command == "--stats":
        show_stats()
    else:
        print(f"❌ Unknown command: {command}")

if __name__ == "__main__":
    main()
