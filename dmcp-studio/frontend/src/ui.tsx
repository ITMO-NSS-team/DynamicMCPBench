// Typed wrappers over the Geist UI primitives. @geist-ui/core ships .d.ts built
// against an older @types/react that marks pointer-capture handlers as required;
// rather than leak `any` at every call site, we re-type each primitive to the
// exact props we use. This file is also the single seam to the kit — swapping
// @geist-ui/core out later means editing only here.
import { Button as GButton, Input as GInput, Textarea as GTextarea } from "@geist-ui/core";
import type { ChangeEvent, FC, ReactNode } from "react";

export interface ButtonProps {
  type?: "default" | "secondary" | "success" | "error" | "warning" | "abort";
  scale?: number;
  loading?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  children?: ReactNode;
}
export const Button = GButton as unknown as FC<ButtonProps>;

export interface InputProps {
  width?: string;
  value?: string;
  placeholder?: string;
  onChange?: (e: ChangeEvent<HTMLInputElement>) => void;
}
export const Input = GInput as unknown as FC<InputProps>;

export interface TextareaProps {
  width?: string;
  rows?: number;
  value?: string;
  placeholder?: string;
  onChange?: (e: ChangeEvent<HTMLTextAreaElement>) => void;
}
export const Textarea = GTextarea as unknown as FC<TextareaProps>;
