-- AVA SmartFuel - Supabase Auth profile tables
-- Run this once in Supabase SQL Editor.

create table if not exists public.user_profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  preferred_fuel text not null default 'SP95-E10',
  consumption_l_100km numeric(4, 1) not null default 6.5,
  tank_liters integer not null default 50,
  language text not null default 'FR',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.favorite_stations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  station_id text not null,
  station_name text not null,
  brand text,
  fuel_type text not null,
  country text,
  lat double precision,
  lon double precision,
  last_price_eur_l numeric(5, 3),
  created_at timestamptz not null default now(),
  unique (user_id, station_id, fuel_type)
);

create table if not exists public.price_alerts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  station_id text,
  fuel_type text not null,
  target_price_eur_l numeric(5, 3),
  enabled boolean not null default true,
  created_at timestamptz not null default now()
);

alter table public.user_profiles enable row level security;
alter table public.favorite_stations enable row level security;
alter table public.price_alerts enable row level security;

drop policy if exists "Users can read own profile" on public.user_profiles;
create policy "Users can read own profile"
on public.user_profiles for select
using (auth.uid() = id);

drop policy if exists "Users can insert own profile" on public.user_profiles;
create policy "Users can insert own profile"
on public.user_profiles for insert
with check (auth.uid() = id);

drop policy if exists "Users can update own profile" on public.user_profiles;
create policy "Users can update own profile"
on public.user_profiles for update
using (auth.uid() = id)
with check (auth.uid() = id);

drop policy if exists "Users can manage own favorites" on public.favorite_stations;
create policy "Users can manage own favorites"
on public.favorite_stations for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "Users can manage own alerts" on public.price_alerts;
create policy "Users can manage own alerts"
on public.price_alerts for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);
