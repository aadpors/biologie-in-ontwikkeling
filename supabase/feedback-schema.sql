-- Een stem per anonieme bezoeker per publicatie.
-- Vereist: Supabase Auth -> Anonymous Sign-ins inschakelen.
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

drop policy if exists "Users can read their own feedback" on public.publication_feedback;
create policy "Users can read their own feedback"
on public.publication_feedback for select to authenticated
using (auth.uid() = user_id);

drop policy if exists "Users can insert their own feedback" on public.publication_feedback;
create policy "Users can insert their own feedback"
on public.publication_feedback for insert to authenticated
with check (auth.uid() = user_id);

drop policy if exists "Users can update their own feedback" on public.publication_feedback;
create policy "Users can update their own feedback"
on public.publication_feedback for update to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "Users can delete their own feedback" on public.publication_feedback;
create policy "Users can delete their own feedback"
on public.publication_feedback for delete to authenticated
using (auth.uid() = user_id);

create or replace function public.publication_feedback_totals()
returns table (
  publication_id text,
  audience text,
  interesting_count bigint,
  not_interesting_count bigint
)
language sql
security definer
set search_path = ''
as $$
  select f.publication_id, f.audience,
    count(*) filter (where f.rating = 'interesting') as interesting_count,
    count(*) filter (where f.rating = 'not') as not_interesting_count
  from public.publication_feedback f
  group by f.publication_id, f.audience;
$$;

revoke all on function public.publication_feedback_totals() from public;
grant execute on function public.publication_feedback_totals() to anon, authenticated;

-- De tabel is niet rechtstreeks leesbaar voor bezoekers; alleen geaggregeerde aantallen
-- worden via de functie beschikbaar gemaakt. Anonieme bezoekers loggen in via Supabase Auth.
