from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "Dev",
    "GIT_AUTHOR_EMAIL": "dev@example.com",
    "GIT_COMMITTER_NAME": "Dev",
    "GIT_COMMITTER_EMAIL": "dev@example.com",
}


class Repo:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.clock = 1_700_000_000
        root.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "-b", "main")

    def git(self, *args: str) -> str:
        env = {**os.environ, **GIT_ENV,
               "GIT_AUTHOR_DATE": f"{self.clock} +0000", "GIT_COMMITTER_DATE": f"{self.clock} +0000"}
        return subprocess.run(["git", "-C", str(self.root), *args], env=env, check=True,
                              capture_output=True, text=True).stdout

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self, message: str, files: dict[str, str] | None = None, hours: float = 1) -> None:
        for rel, text in (files or {}).items():
            self.write(rel, text)
        self.clock += int(hours * 3600)
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path)


VIBEY_MAIN = '''\
#include <iostream>
#include <cstdio>
#include "inventory.h"

// ============================================
// Inventory Management System
// ============================================

int main() {
    // Initialize the inventory
    Inventory* inventory = new Inventory();
    if (inventory == nullptr) {
        std::cerr << "❌ Failed to allocate inventory" << std::endl;
        return 1;
    }

    // Step 1: Load the items from disk
    inventory->loadItems("items.txt");

    // Now we print the summary — this gives the user an overview
    printf("✅ Loaded %d items\\n", inventory->count());

    // In a real application, you would want to persist this to a database
    // ... rest of the code remains the same

    // CRITICAL: Free the inventory to avoid memory leaks
    delete inventory;
    return 0;
}
'''

VIBEY_INVENTORY_H = '''\
#pragma once
#ifndef INVENTORY_H
#define INVENTORY_H

#include <string>
#include <vector>

class Inventory {
public:
    void loadItems(const std::string& path);
    int count() const { return static_cast<int>(items.size()); }
private:
    std::vector<std::string> items;
};

#endif // INVENTORY_H
'''

VIBEY_INVENTORY_CPP = '''\
#include "inventory.h"
#include <fstream>
#include <iostream>

// Helper function to trim whitespace from a string
static std::string trimWhitespace(const std::string& input) {
    size_t start = input.find_first_not_of(" \\t");
    size_t end = input.find_last_not_of(" \\t");
    return start == std::string::npos ? "" : input.substr(start, end - start + 1);
}

// FIXED: now correctly handles empty lines
void Inventory::loadItems(const std::string& path) {
    // Open the file
    std::ifstream file(path);
    if (!file.is_open()) {
        std::cerr << "⚠️ Could not open " << path << std::endl;
        return;
    }
    std::string line;
    // Loop through each line in the file
    while (std::getline(file, line)) {
        if (line.empty()) { continue; }
        // Add the item to the items
        items.push_back(line);
    }
    // Close the file
    file.close();
}

void loadItemsFromBackup(const std::string& path, std::vector<std::string>& items) {
    std::ifstream file(path);
    if (!file.is_open()) {
        std::cerr << "⚠️ Could not open " << path << std::endl;
        return;
    }
    std::string line;
    while (std::getline(file, line)) {
        if (line.empty()) { continue; }
        items.push_back(line);
    }
    file.close();
}
'''

VIBEY_README = '''\
# 📦 Inventory Manager

A comprehensive, robust and blazing-fast inventory system built with modern C++.

## ✨ Features

- ✅ Load items from disk
- ✅ Seamless error handling
- 🚀 Production-ready

## 📁 Project Structure

```
├── main.cpp
└── inventory.cpp
```
'''

AI_TRAILER = "\n\nCo-Authored-By: Claude <noreply@anthropic.com>"
LLM_BODY = """

- Add comprehensive error handling for file loading
- Enhance output with status indicators
- Ensure robust memory management"""


@pytest.fixture
def vibey_repo(tmp_path: Path) -> Repo:
    repo = Repo(tmp_path / "vibey")
    repo.commit("Initial commit", {"README.md": "# inventory\n"})
    repo.commit("Implement comprehensive inventory management system" + LLM_BODY + AI_TRAILER, {
        "main.cpp": VIBEY_MAIN,
        "inventory.h": VIBEY_INVENTORY_H,
        "inventory.cpp": VIBEY_INVENTORY_CPP,
        "README.md": VIBEY_README,
        "CLAUDE.md": "# Project notes\nUse C++17.\n",
    }, hours=0.2)
    for msg in ("fix build", "fix build again", "try fixing linker error", "still broken, attempt 3"):
        repo.commit(msg + AI_TRAILER, {"main.cpp": VIBEY_MAIN + f"// {msg}\n"}, hours=0.1)
    repo.commit("Enhance error handling and ensure robust output" + LLM_BODY + AI_TRAILER, {
        "IMPLEMENTATION_SUMMARY.md": "# Implementation Summary\n\nAll features complete! ✅\n",
        "FIXES_APPLIED.md": "# Fixes\n",
        "main_old.cpp": VIBEY_MAIN,
        "debug_loader.py": "print('debug')\n",
    }, hours=0.1)
    return repo


CLEAN_LIST_H = '''\
#ifndef LIST_H
#define LIST_H

#include <stddef.h>

struct node {
    int value;
    struct node *next;
};

struct node *list_push(struct node *head, int value);
size_t list_len(const struct node *head);
void list_free(struct node *head);

#endif
'''

CLEAN_LIST_C = '''\
#include <stdlib.h>
#include "list.h"

struct node *list_push(struct node *head, int value)
{
    struct node *n = malloc(sizeof *n);
    if (!n)
        return NULL;
    n->value = value;
    n->next = head;
    return n;
}

size_t list_len(const struct node *head)
{
    size_t len = 0;
    for (; head; head = head->next)
        len++;
    return len;
}

void list_free(struct node *head)
{
    while (head) {
        struct node *next = head->next;
        free(head);
        head = next;
    }
}
'''

CLEAN_MAIN_C = '''\
#include <stdio.h>
#include "list.h"

static int sum(const struct node *head)
{
    int total = 0;
    for (; head; head = head->next)
        total += head->value;
    return total;
}

int main(void)
{
    struct node *list = NULL;
    for (int i = 1; i <= 10; i++)
        list = list_push(list, i);
    /* list_push returns NULL on allocation failure, losing the list; fine for a demo */
    printf("%zu items, sum %d\\n", list_len(list), sum(list));
    list_free(list);
    return 0;
}
'''


@pytest.fixture
def clean_repo(tmp_path: Path) -> Repo:
    repo = Repo(tmp_path / "clean")
    repo.commit("list: singly linked list", {"list.h": CLEAN_LIST_H, "list.c": CLEAN_LIST_C})
    repo.commit("main: sum a small list", {"main.c": CLEAN_MAIN_C}, hours=26)
    repo.commit("README", {"README.md": "# lists\n\nA tiny linked list. `make && ./main`\n"}, hours=3)
    repo.commit("list: handle malloc failure in list_push", {"list.c": CLEAN_LIST_C + "\n"}, hours=50)
    return repo
