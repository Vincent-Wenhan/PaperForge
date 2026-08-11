"use client";

export interface TreeNode {
  path: string;
  type: "file" | "directory";
  size?: number;
  children?: TreeNode[];
}

export interface EditorTab {
  path: string;
  content: string;
  dirty: boolean;
  saveState?: "saved" | "saving" | "error";
}
