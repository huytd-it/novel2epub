import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";

export interface Relation {
  b_source: string;
  b_target: string;
  from_chapter: number;
  a_calls_b: string;
  a_self: string;
  note: string;
  to_chapter: number | null;
  a_calls_b_raw: string;
  a_self_raw: string;
  evidence: string;
  inferred: boolean;
  confidence: string;
}

export interface CharacterEntry {
  source: string;
  target: string;
  aliases: string;
  gender: string;
  self_pronoun: string;
  narrator_ref: string;
  role_note: string;
  importance: string;
  aliases_vi: string;
  relations: Relation[];
}

export interface PendingCharacter {
  source: string;
  target?: string;
  aliases_raw?: string[];
  aliases_vi?: string[];
  gender?: string;
  self_pronoun?: string;
  narrator_ref?: string;
  role_note?: string;
  importance?: string;
  update_only?: boolean;
  new_aliases_raw?: string[];
  new_aliases_vi?: string[];
}

export interface PendingRelation {
  a_source: string;
  b_source: string;
  from_chapter?: number;
  to_chapter?: number | null;
  a_calls_b_vi?: string;
  a_self_vi?: string;
  a_calls_b_raw?: string;
  a_self_raw?: string;
  reason?: string;
  evidence?: string;
  inferred?: boolean;
  confidence?: string;
}

const listKey = (slug: string) => ["characters", slug] as const;
const pendingKey = (slug: string) => ["characters-pending", slug] as const;

export function useCharacters(slug: string) {
  return useQuery({
    queryKey: listKey(slug),
    queryFn: () =>
      api.get<{ entries: CharacterEntry[]; total: number }>(`/api/ebook/${slug}/characters/list`),
    enabled: Boolean(slug),
  });
}

export function useCharactersPending(slug: string) {
  return useQuery({
    queryKey: pendingKey(slug),
    queryFn: () =>
      api.get<{
        characters: PendingCharacter[];
        relations: PendingRelation[];
        counts: { characters: number; relations: number };
      }>(`/api/ebook/${slug}/characters/pending`),
    enabled: Boolean(slug),
  });
}

function useInvalidate(slug: string) {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: listKey(slug) });
}

export function useUpsertCharacter(slug: string) {
  const invalidate = useInvalidate(slug);
  return useMutation({
    mutationFn: (vars: {
      source: string;
      target: string;
      aliases: string;
      gender: string;
      self_pronoun: string;
      narrator_ref: string;
      role_note: string;
      importance: string;
      originalSource: string;
    }) =>
      api.post<{ ok: boolean }>(`/api/ebook/${slug}/characters/entry`, {
        form: {
          source: vars.source,
          target: vars.target,
          aliases: vars.aliases,
          gender: vars.gender,
          self_pronoun: vars.self_pronoun,
          narrator_ref: vars.narrator_ref,
          role_note: vars.role_note,
          importance: vars.importance,
          original_source: vars.originalSource,
        },
      }),
    onSuccess: invalidate,
  });
}

export function useDeleteCharacters(slug: string) {
  const invalidate = useInvalidate(slug);
  return useMutation({
    mutationFn: (sources: string[]) =>
      api.post<{ ok: boolean; removed: number }>(`/api/ebook/${slug}/characters/delete`, {
        form: { sources: sources.join("|") },
      }),
    onSuccess: invalidate,
  });
}

export function useUpsertRelation(slug: string) {
  const invalidate = useInvalidate(slug);
  return useMutation({
    mutationFn: (vars: {
      a_source: string;
      b_source: string;
      from_chapter: number;
      a_calls_b: string;
      a_self: string;
      note: string;
    }) => api.post<{ ok: boolean }>(`/api/ebook/${slug}/characters/relation`, { form: vars }),
    onSuccess: invalidate,
  });
}

export function useDeleteRelation(slug: string) {
  const invalidate = useInvalidate(slug);
  return useMutation({
    mutationFn: (vars: { a_source: string; b_source: string; from_chapter: number }) =>
      api.post<{ ok: boolean; removed: number }>(`/api/ebook/${slug}/characters/relation/delete`, {
        form: vars,
      }),
    onSuccess: invalidate,
  });
}

function useInvalidatePending(slug: string) {
  const client = useQueryClient();
  return () => {
    client.invalidateQueries({ queryKey: pendingKey(slug) });
    client.invalidateQueries({ queryKey: listKey(slug) });
  };
}

export function useApprovePending(slug: string) {
  const invalidate = useInvalidatePending(slug);
  return useMutation({
    mutationFn: (vars: { characters: PendingCharacter[]; relations: PendingRelation[] }) =>
      api.post<{
        approved_characters: number;
        approved_relations: number;
        blocked: string[];
        remaining: { characters: number; relations: number };
      }>(`/api/ebook/${slug}/characters/pending/approve`, { body: vars }),
    onSuccess: invalidate,
  });
}

export function useClearPending(slug: string) {
  const invalidate = useInvalidatePending(slug);
  return useMutation({
    mutationFn: (vars: { characters?: string[]; relations?: PendingRelation[]; all?: boolean }) =>
      api.post<{ cleared: number }>(`/api/ebook/${slug}/characters/pending/clear`, {
        body: vars.all
          ? { all: true }
          : { characters: vars.characters ?? [], relations: vars.relations ?? [] },
      }),
    onSuccess: invalidate,
  });
}
