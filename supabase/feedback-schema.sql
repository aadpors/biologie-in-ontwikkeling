-- Biologie in ontwikkeling: anonieme, persoonlijke publicatiestemmen.
-- Anonymous Sign-Ins moeten in Supabase Auth ingeschakeld zijn.

create table if not exists public.publication_feedback (
  user_id uuid not null references auth.users(id) on delete cascade,
  publication_id text not null,
  audience text not null check (audience in ('Havo','Vwo','Beide')),
  rating text not null check (rating in ('interesting','not')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, publication_id)
);

alter table public.publication_feedback enable row level security;

-- Data API-toegang expliciet verlenen; nieuwe Supabase-projecten exposen
-- tabellen niet meer automatisch. RLS beperkt dit tot de eigen stem.
revoke all on table public.publication_feedback from anon, public;
grant select, insert, update, delete on table public.publication_feedback to authenticated;

create or replace function public.set_feedback_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

revoke all on function public.set_feedback_updated_at() from public, anon, authenticated;
drop trigger if exists publication_feedback_updated_at on public.publication_feedback;
create trigger publication_feedback_updated_at
before update on public.publication_feedback
for each row execute function public.set_feedback_updated_at();

drop policy if exists "Users can read their own feedback" on public.publication_feedback;
create policy "Users can read their own feedback"
on public.publication_feedback for select to authenticated
using (
  (select auth.uid()) = user_id
  and ((select auth.jwt()) ->> 'is_anonymous') = 'true'
);

drop policy if exists "Users can insert their own feedback" on public.publication_feedback;
create policy "Users can insert their own feedback"
on public.publication_feedback for insert to authenticated
with check (
  (select auth.uid()) = user_id
  and ((select auth.jwt()) ->> 'is_anonymous') = 'true'
);

drop policy if exists "Users can update their own feedback" on public.publication_feedback;
create policy "Users can update their own feedback"
on public.publication_feedback for update to authenticated
using (
  (select auth.uid()) = user_id
  and ((select auth.jwt()) ->> 'is_anonymous') = 'true'
)
with check (
  (select auth.uid()) = user_id
  and ((select auth.jwt()) ->> 'is_anonymous') = 'true'
);

drop policy if exists "Users can delete their own feedback" on public.publication_feedback;
create policy "Users can delete their own feedback"
on public.publication_feedback for delete to authenticated
using (
  (select auth.uid()) = user_id
  and ((select auth.jwt()) ->> 'is_anonymous') = 'true'
);

-- De aggregatefunctie draait met beperkte elevated privileges in een niet-
-- geëxposeerd schema. Alleen anonieme ingelogde bezoekers kunnen haar aanroepen.
create schema if not exists private;
revoke all on schema private from public, anon;
grant usage on schema private to authenticated;

create or replace function private.publication_feedback_totals()
returns table (
  publication_id text,
  audience text,
  interesting_count bigint,
  not_interesting_count bigint
)
language sql
stable
security definer
set search_path = ''
as $$
  select f.publication_id, f.audience,
    count(*) filter (where f.rating = 'interesting') as interesting_count,
    count(*) filter (where f.rating = 'not') as not_interesting_count
  from public.publication_feedback f
  where auth.uid() is not null
    and auth.jwt() ->> 'is_anonymous' = 'true'
  group by f.publication_id, f.audience;
$$;

revoke all on function private.publication_feedback_totals() from public, anon, authenticated;
grant execute on function private.publication_feedback_totals() to authenticated;

create or replace function public.publication_feedback_totals()
returns table (
  publication_id text,
  audience text,
  interesting_count bigint,
  not_interesting_count bigint
)
language sql
stable
security invoker
set search_path = ''
as $$
  select * from private.publication_feedback_totals();
$$;

revoke all on function public.publication_feedback_totals() from public, anon, authenticated;
grant execute on function public.publication_feedback_totals() to authenticated;
