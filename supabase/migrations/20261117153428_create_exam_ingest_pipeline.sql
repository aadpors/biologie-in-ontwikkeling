create table if not exists public.exam_ingest_jobs (
  id uuid primary key default gen_random_uuid(),
  original_filename text not null,
  storage_path text not null unique,
  file_size_bytes bigint not null check (file_size_bytes > 0),
  mime_type text not null,
  status text not null default 'uploaded'
    check (status in ('uploaded','queued','processing','review_required','ready','failed')),
  stage text not null default 'Upload ontvangen',
  progress integer not null default 0 check (progress between 0 and 100),
  message text,
  detected_metadata jsonb not null default '{}'::jsonb,
  error_details jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  published_at timestamptz
);
create index if not exists exam_ingest_jobs_created_at_idx on public.exam_ingest_jobs (created_at desc);
create index if not exists exam_ingest_jobs_status_idx on public.exam_ingest_jobs (status);

create table if not exists public.exam_ingest_events (
  id bigint generated always as identity primary key,
  job_id uuid not null references public.exam_ingest_jobs(id) on delete cascade,
  level text not null default 'info' check (level in ('info','warning','error','success')),
  stage text,
  message text not null,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists exam_ingest_events_job_created_idx on public.exam_ingest_events (job_id, created_at);

alter table public.exam_ingest_jobs enable row level security;
alter table public.exam_ingest_events enable row level security;
revoke all on public.exam_ingest_jobs from public;
revoke all on public.exam_ingest_events from public;
grant select, insert, update, delete on public.exam_ingest_jobs to anon;
grant select, insert, update, delete on public.exam_ingest_events to anon;

drop policy if exists "Temporary hidden-admin access to exam jobs" on public.exam_ingest_jobs;
create policy "Temporary hidden-admin access to exam jobs"
on public.exam_ingest_jobs for all to anon using (true) with check (true);
drop policy if exists "Temporary hidden-admin access to exam events" on public.exam_ingest_events;
create policy "Temporary hidden-admin access to exam events"
on public.exam_ingest_events for all to anon using (true) with check (true);

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('exam-inbox','exam-inbox',false,524288000,
  array['application/pdf','application/zip','application/x-zip-compressed','application/octet-stream'])
on conflict (id) do update set public=false,file_size_limit=524288000,allowed_mime_types=excluded.allowed_mime_types;

drop policy if exists "Temporary hidden-admin upload to exam inbox" on storage.objects;
create policy "Temporary hidden-admin upload to exam inbox"
on storage.objects for insert to anon with check (bucket_id='exam-inbox');
drop policy if exists "Temporary hidden-admin read exam inbox" on storage.objects;
create policy "Temporary hidden-admin read exam inbox"
on storage.objects for select to anon using (bucket_id='exam-inbox');
drop policy if exists "Temporary hidden-admin update exam inbox" on storage.objects;
create policy "Temporary hidden-admin update exam inbox"
on storage.objects for update to anon using (bucket_id='exam-inbox') with check (bucket_id='exam-inbox');
drop policy if exists "Temporary hidden-admin delete exam inbox" on storage.objects;
create policy "Temporary hidden-admin delete exam inbox"
on storage.objects for delete to anon using (bucket_id='exam-inbox');
