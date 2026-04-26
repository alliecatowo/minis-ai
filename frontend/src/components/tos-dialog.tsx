"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface TosDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  onAgree: () => void | Promise<void>;
  onCancel: () => void;
  loading?: boolean;
}

export function TosDialog({
  open,
  onOpenChange,
  title,
  description,
  onAgree,
  onCancel,
  loading = false,
}: TosDialogProps) {
  const [tosContent, setTosContent] = useState<string>("Loading terms...");

  useEffect(() => {
    let active = true;
    void fetch("/tos.md")
      .then((response) => response.text())
      .then((text) => {
        if (active) setTosContent(text);
      })
      .catch(() => {
        if (active) setTosContent("Unable to load terms. Please try again.");
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>

        <div className="max-h-[50vh] overflow-y-auto rounded-md border border-border/70 p-4 text-sm leading-6">
          <article className="prose prose-sm dark:prose-invert max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{tosContent}</ReactMarkdown>
          </article>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={loading}>
            Cancel
          </Button>
          <Button onClick={onAgree} disabled={loading}>
            {loading ? "Saving..." : "I agree"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
