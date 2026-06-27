"use client";

// Contacts: the people an org reaches out to. A clean table (name, email, role,
// linked account) with add / edit / delete, plus a self-contained modal form
// (no external dialog dependency, so it works offline). Contacts back the email
// recipient picker in the Execute panel and the chat "email this to <contact>"
// flow. Grayscale + Claude orange, Geist.

import * as React from "react";
import {
  Contact2,
  Loader2,
  Mail,
  Pencil,
  Plus,
  Search,
  Trash2,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/ui/page-header";
import { toast } from "@/components/ui/toast";
import { getAccounts } from "@/lib/api";
import {
  createContact,
  deleteContact,
  listContacts,
  updateContact,
  type Contact,
  type ContactInput,
} from "@/lib/api/contacts";
import type { Account } from "@/lib/types";

function Field({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-xs font-medium text-foreground">
        {label}
      </label>
      {children}
      {hint ? <p className="text-[11px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

interface ContactDialogProps {
  open: boolean;
  // When editing, the contact to seed the form with; null to create a new one.
  contact: Contact | null;
  accounts: Account[];
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}

function ContactDialog({
  open,
  contact,
  accounts,
  onOpenChange,
  onSaved,
}: ContactDialogProps) {
  const editing = contact !== null;
  const [name, setName] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [role, setRole] = React.useState("");
  const [accountId, setAccountId] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);

  // Seed the form whenever the dialog opens (create resets, edit prefills).
  React.useEffect(() => {
    if (!open) return;
    setName(contact?.name ?? "");
    setEmail(contact?.email ?? "");
    setRole(contact?.role ?? "");
    setAccountId(contact?.account_id ?? "");
  }, [open, contact]);

  // Close on Escape and lock body scroll while open.
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onOpenChange(false);
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onOpenChange]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;
    if (!name.trim()) {
      toast("Name is required", { variant: "error" });
      return;
    }
    if (!email.trim()) {
      toast("Email is required", { variant: "error" });
      return;
    }

    const payload: ContactInput = {
      name: name.trim(),
      email: email.trim(),
      role: role.trim() || undefined,
      account_id: accountId || undefined,
    };

    setSubmitting(true);
    try {
      if (editing && contact) {
        await updateContact(contact.id, payload);
        toast(`Updated ${payload.name}`, { variant: "success" });
      } else {
        await createContact(payload);
        toast(`Added ${payload.name}`, {
          variant: "success",
          description: "Available now in the email recipient picker.",
        });
      }
      onOpenChange(false);
      onSaved();
    } catch {
      toast(
        editing ? "Could not update the contact" : "Could not add the contact",
        { variant: "error", description: "Check your connection and try again." },
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4 backdrop-blur-sm"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onOpenChange(false);
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="contact-dialog-title"
        className="flex max-h-[90vh] w-full max-w-md flex-col overflow-hidden rounded-xl border border-border bg-card shadow-lg"
      >
        <div className="flex shrink-0 items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div>
            <div className="text-eyebrow">{editing ? "Edit contact" : "New contact"}</div>
            <h2
              id="contact-dialog-title"
              className="mt-0.5 text-lg font-semibold text-foreground"
            >
              {editing ? "Update contact" : "Add a contact"}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              A name and email is all you need. Link an account to find them in
              context.
            </p>
          </div>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            aria-label="Close"
            className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={onSubmit} className="flex min-h-0 flex-1 flex-col">
          <div className="flex-1 space-y-4 overflow-y-auto px-5 py-5">
            <Field label="Name" htmlFor="contact-name">
              <Input
                id="contact-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Dana Lee"
                autoFocus
                required
              />
            </Field>
            <Field label="Email" htmlFor="contact-email">
              <Input
                id="contact-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="dana@northwind.com"
                required
              />
            </Field>
            <Field label="Role" htmlFor="contact-role" hint="e.g. Economic buyer, Champion, Admin.">
              <Input
                id="contact-role"
                value={role}
                onChange={(e) => setRole(e.target.value)}
                placeholder="Economic buyer"
              />
            </Field>
            <Field label="Linked account" htmlFor="contact-account">
              <Select
                id="contact-account"
                value={accountId}
                onChange={(e) => setAccountId(e.target.value)}
              >
                <option value="">No linked account</option>
                {accounts.map((a) => (
                  <option key={a.account_id} value={a.account_id}>
                    {a.name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <div className="flex shrink-0 items-center justify-end gap-2 border-t border-border bg-card px-5 py-4">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Plus className="h-4 w-4" />
              )}
              {editing ? "Save contact" : "Add contact"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function ContactsPage() {
  const [contacts, setContacts] = React.useState<Contact[] | null>(null);
  const [accounts, setAccounts] = React.useState<Account[]>([]);
  const [query, setQuery] = React.useState("");
  const [nonce, setNonce] = React.useState(0);
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<Contact | null>(null);
  const [deletingId, setDeletingId] = React.useState<string | null>(null);

  React.useEffect(() => {
    const ctrl = new AbortController();
    void listContacts(ctrl.signal).then(setContacts);
    return () => ctrl.abort();
  }, [nonce]);

  // Accounts power the linked-account select and the table's account labels.
  React.useEffect(() => {
    const ctrl = new AbortController();
    void getAccounts(ctrl.signal).then(setAccounts);
    return () => ctrl.abort();
  }, []);

  const refresh = React.useCallback(() => setNonce((n) => n + 1), []);

  const accountName = React.useCallback(
    (id?: string | null) => {
      if (!id) return null;
      return accounts.find((a) => a.account_id === id)?.name ?? id;
    },
    [accounts],
  );

  function openCreate() {
    setEditing(null);
    setDialogOpen(true);
  }

  function openEdit(contact: Contact) {
    setEditing(contact);
    setDialogOpen(true);
  }

  async function onDelete(contact: Contact) {
    setDeletingId(contact.id);
    try {
      await deleteContact(contact.id);
      toast(`Removed ${contact.name}`, { variant: "success" });
      refresh();
    } catch {
      toast("Could not remove the contact", { variant: "error" });
    } finally {
      setDeletingId(null);
    }
  }

  const filtered = React.useMemo(() => {
    if (!contacts) return [];
    const q = query.trim().toLowerCase();
    if (!q) return contacts;
    return contacts.filter(
      (c) =>
        c.name.toLowerCase().includes(q) ||
        c.email.toLowerCase().includes(q) ||
        (c.role ?? "").toLowerCase().includes(q),
    );
  }, [contacts, query]);

  const isEmpty = contacts !== null && contacts.length === 0;

  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-8">
      <PageHeader
        eyebrow="Directory"
        title="Contacts"
        description="The people you reach out to. Pick them as recipients when you send a recommendation."
        actions={
          <>
            {!isEmpty && (
              <div className="relative w-full sm:w-56">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search contacts"
                  className="pl-9"
                />
              </div>
            )}
            <Button type="button" onClick={openCreate}>
              <Plus className="h-4 w-4" />
              Add contact
            </Button>
          </>
        }
      />

      {contacts === null ? (
        <div className="panel p-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="flex items-center gap-4 py-3">
              <Skeleton className="h-4 w-48" />
              <Skeleton className="h-4 w-40" />
              <Skeleton className="ml-auto h-4 w-16" />
            </div>
          ))}
        </div>
      ) : isEmpty ? (
        <div className="panel flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
            <Contact2 className="h-6 w-6" />
          </div>
          <div>
            <p className="text-sm font-medium text-foreground">No contacts yet</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Add the people you email so you can target them when sending a play.
            </p>
          </div>
          <Button type="button" onClick={openCreate} className="mt-1">
            <Plus className="h-4 w-4" />
            Add your first contact
          </Button>
        </div>
      ) : (
        <div className="panel overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th className="px-4 py-3 font-medium">Name</th>
                <th className="px-4 py-3 font-medium">Email</th>
                <th className="px-4 py-3 font-medium">Role</th>
                <th className="px-4 py-3 font-medium">Linked account</th>
                <th className="px-4 py-3 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((c) => (
                <tr
                  key={c.id}
                  className="border-b border-border/60 last:border-0 hover:bg-secondary/40"
                >
                  <td className="px-4 py-3 font-medium text-foreground">{c.name}</td>
                  <td className="px-4 py-3">
                    <a
                      href={`mailto:${c.email}`}
                      className="inline-flex items-center gap-1.5 text-muted-foreground hover:text-primary"
                    >
                      <Mail className="h-3.5 w-3.5" />
                      {c.email}
                    </a>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {c.role || <span className="text-muted-foreground/50">-</span>}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {accountName(c.account_id) || (
                      <span className="text-muted-foreground/50">-</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        aria-label={`Edit ${c.name}`}
                        onClick={() => openEdit(c)}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        aria-label={`Delete ${c.name}`}
                        disabled={deletingId === c.id}
                        onClick={() => onDelete(c)}
                      >
                        {deletingId === c.id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Trash2 className="h-4 w-4" />
                        )}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ContactDialog
        open={dialogOpen}
        contact={editing}
        accounts={accounts}
        onOpenChange={setDialogOpen}
        onSaved={refresh}
      />
    </div>
  );
}
