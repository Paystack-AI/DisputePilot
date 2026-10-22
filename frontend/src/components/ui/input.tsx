import { forwardRef } from 'react';
import { cn } from '@/lib/cn';

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  error?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, error, ...props },
  ref,
) {
  return <input ref={ref} className={cn('field', error && 'field-error', className)} {...props} />;
});

export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  error?: boolean;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { className, error, ...props },
  ref,
) {
  return (
    <textarea
      ref={ref}
      className={cn('field min-h-28 resize-y leading-6', error && 'field-error', className)}
      {...props}
    />
  );
});

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  error?: boolean;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { className, error, children, ...props },
  ref,
) {
  return (
    <select
      ref={ref}
      className={cn(
        'field appearance-none bg-[url("data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 fill=%27none%27 viewBox=%270 0 24 24%27 stroke=%27%23627b92%27 stroke-width=%272%27%3E%3Cpath d=%27m6 9 6 6 6-6%27/%3E%3C/svg%3E")] bg-[length:18px] bg-[right_12px_center] bg-no-repeat pr-10',
        error && 'field-error',
        className,
      )}
      {...props}
    >
      {children}
    </select>
  );
});

export function Label({
  className,
  children,
  ...props
}: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label className={cn('label', className)} {...props}>
      {children}
    </label>
  );
}

export function FieldError({ children }: { children?: React.ReactNode }) {
  if (!children) return null;
  return <p className="mt-1.5 text-[12px] font-medium text-danger">{children}</p>;
}

export function FieldHint({ children }: { children?: React.ReactNode }) {
  if (!children) return null;
  return <p className="mt-1.5 text-[12px] leading-5 text-ink-500">{children}</p>;
}
