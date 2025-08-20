import discord
from discord.ext import commands, tasks
import asyncio
import json
from datetime import datetime, timezone, timedelta
import os
import re
from typing import Dict, List, Optional

# Bot configuration
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
GUILD_ID = int(os.getenv('GUILD_ID', '0'))
LEADERBOARD_CHANNEL = int(os.getenv('LEADERBOARD_CHANNEL', '0'))

class WeeklyCompetition:
    def __init__(self):
        self.data_file = "competition_data.json"
        self.current_week = self.get_current_week()
        self.player_times = {}
        self.player_names = {}
        self.author_times = {}
        self.week_maps = {
            1: "Map 1 - Short Track Alpha",
            2: "Map 2 - Short Track Beta", 
            3: "Map 3 - Short Track Gamma",
            4: "Map 4 - Short Track Delta",
            5: "Map 5 - Short Track Epsilon"
        }
        self.load_data()

    def load_data(self):
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                
                self.player_names = {int(k): v for k, v in data.get('player_names', {}).items()}
                
                saved_week = data.get('current_week', '')
                if saved_week == self.current_week:
                    self.player_times = {int(k): {int(map_k): map_v for map_k, map_v in v.items()} 
                                       for k, v in data.get('player_times', {}).items()}
                    self.author_times = {int(k): v for k, v in data.get('author_times', {}).items()}
                    print(f"📊 Loaded existing data for week {self.current_week}")
                else:
                    self.player_times = {}
                    self.author_times = {}
                    print(f"🆕 New week detected! Reset times, kept {len(self.player_names)} registered players")
                    self.save_data()
            else:
                print("📝 No existing data file found, starting fresh")
        except Exception as e:
            print(f"⚠️ Error loading data: {e}")

    def save_data(self):
        try:
            data = {
                'current_week': self.current_week,
                'player_names': self.player_names,
                'player_times': self.player_times,
                'author_times': self.author_times,
                'last_updated': datetime.now().isoformat()
            }
            
            with open(self.data_file, 'w') as f:
                json.dump(data, f, indent=2)
            
        except Exception as e:
            print(f"⚠️ Error saving data: {e}")

    def get_current_week(self) -> str:
        now = datetime.now()
        year = now.year
        week = now.isocalendar()[1]
        return f"{year}-W{week:02d}"

    def register_player(self, discord_id: int, tm_username: str):
        self.player_names[discord_id] = tm_username
        if discord_id not in self.player_times:
            self.player_times[discord_id] = {}
        self.save_data()

    def add_time(self, discord_id: int, map_num: int, time_ms: int) -> bool:
        if discord_id not in self.player_names:
            return False
        if map_num not in range(1, 6):
            return False
        if discord_id not in self.player_times:
            self.player_times[discord_id] = {}
        self.player_times[discord_id][map_num] = time_ms
        self.save_data()
        return True

    def set_author_time(self, map_num: int, time_ms: int) -> bool:
        if map_num not in range(1, 6):
            return False
        self.author_times[map_num] = time_ms
        self.save_data()
        return True

    def get_map_leaderboard(self, map_num: int) -> List[Dict]:
        if map_num not in range(1, 6):
            return []

        players = []
        for discord_id in self.player_times:
            if map_num in self.player_times[discord_id]:
                time = self.player_times[discord_id][map_num]
                players.append({
                    'discord_id': discord_id,
                    'tm_username': self.player_names.get(discord_id, 'Unknown'),
                    'time': time
                })

        sorted_players = sorted(players, key=lambda x: x['time'])
        
        if sorted_players:
            first_time = sorted_players[0]['time']
            for player in sorted_players:
                if player['time'] == first_time:
                    player['split'] = None
                else:
                    player['split'] = player['time'] - first_time

        return sorted_players

    def get_overall_leaderboard(self) -> List[Dict]:
        players = []

        for discord_id in self.player_times:
            times = self.player_times[discord_id]
            if not times:
                continue

            author_medals = 0
            for map_num, time_ms in times.items():
                if map_num in self.author_times:
                    if time_ms <= self.author_times[map_num]:
                        author_medals += 1

            players.append({
                'discord_id': discord_id,
                'tm_username': self.player_names.get(discord_id, 'Unknown'),
                'maps_completed': len(times),
                'individual_times': times,
                'author_medals': author_medals
            })

        return sorted(players, key=lambda x: (-x['maps_completed'], -x['author_medals'], x['tm_username'].lower()))

    def reset_week(self):
        old_week = self.current_week
        self.current_week = self.get_current_week()
        self.player_times = {}
        self.author_times = {}
        self.save_data()
        print(f"🔄 Week reset from {old_week} to {self.current_week}")

class WeeklyShortsBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!tm ', intents=intents)
        self.competition = WeeklyCompetition()

    async def setup_hook(self):
        self.weekly_reset_check.start()
        print("🏁 Trackmania Weekly Shorts Bot is ready!")
        print(f"📅 Current competition week: {self.competition.current_week}")

    @tasks.loop(hours=1)
    async def weekly_reset_check(self):
        current_week = self.competition.get_current_week()
        if current_week != self.competition.current_week:
            await self.handle_week_reset(current_week)

    async def handle_week_reset(self, new_week: str):
        channel = self.get_channel(LEADERBOARD_CHANNEL)
        if channel:
            old_week = self.competition.current_week
            self.competition.reset_week()
            
            embed = discord.Embed(
                title=f"🆕 New Week Started - {new_week}",
                description="Time for new Weekly Shorts! Register and submit your times.",
                color=discord.Color.blue()
            )
            await channel.send(embed=embed)

bot = WeeklyShortsBot()

@bot.event
async def on_ready():
    print(f'Bot logged in as {bot.user}!')

@bot.command(name='register')
async def register_player(ctx, *, trackmania_username: str):
    if len(trackmania_username) > 50:
        await ctx.send("❌ Username too long! Please use a shorter name.")
        return
    bot.competition.register_player(ctx.author.id, trackmania_username)
    await ctx.send(f"✅ Registered `{trackmania_username}` for {ctx.author.mention}!")

@bot.command(name='time', aliases=['submit', 't'])
async def submit_time(ctx, map_num: int, *, time_str: str):
    if ctx.author.id not in bot.competition.player_names:
        await ctx.send("❌ Please register first with `!tm register <your_trackmania_username>`")
        return

    if map_num not in range(1, 6):
        await ctx.send("❌ Map number must be between 1 and 5!")
        return

    time_ms = parse_time(time_str)
    if time_ms is None:
        await ctx.send("❌ Invalid time format! Use formats like: `1:23.456`, `83.456`, or `83456` (ms)")
        return

    if not (1000 <= time_ms <= 600000):
        await ctx.send("❌ Time seems unreasonable (must be between 1 second and 10 minutes)")
        return

    success = bot.competition.add_time(ctx.author.id, map_num, time_ms)
    if success:
        formatted_time = format_time(time_ms)
        tm_username = bot.competition.player_names[ctx.author.id]

        embed = discord.Embed(title="⏱️ Time Submitted!", color=discord.Color.green())
        embed.add_field(name="Player", value=tm_username, inline=True)
        embed.add_field(name="Map", value=f"#{map_num}", inline=True)
        embed.add_field(name="Time", value=formatted_time, inline=True)

        if map_num in bot.competition.author_times:
            author_time = bot.competition.author_times[map_num]
            if time_ms <= author_time:
                embed.add_field(name="🏅", value="Author Medal!", inline=True)

        await ctx.send(embed=embed)

@bot.command(name='author')
@commands.has_permissions(administrator=True)
async def set_author_time(ctx, map_num: int, *, time_str: str):
    if map_num not in range(1, 6):
        await ctx.send("❌ Map number must be between 1 and 5!")
        return

    time_ms = parse_time(time_str)
    if time_ms is None:
        await ctx.send("❌ Invalid time format!")
        return

    if not (1000 <= time_ms <= 600000):
        await ctx.send("❌ Time seems unreasonable")
        return

    success = bot.competition.set_author_time(map_num, time_ms)
    if success:
        formatted_time = format_time(time_ms)
        embed = discord.Embed(title="🏅 Author Time Set!", color=discord.Color.gold())
        embed.add_field(name="Map", value=f"#{map_num}", inline=True)
        embed.add_field(name="Author Time", value=formatted_time, inline=True)
        await ctx.send(embed=embed)

@bot.command(name='leaderboard', aliases=['lb'])
async def show_leaderboard(ctx):
    leaderboard = bot.competition.get_overall_leaderboard()
    if not leaderboard:
        await ctx.send("📊 No times submitted yet this week!")
        return

    embed = discord.Embed(
        title=f"🏁 Weekly Shorts Leaderboard - {bot.competition.current_week}",
        description="All player times across the 5 maps",
        color=discord.Color.green()
    )

    for i, player in enumerate(leaderboard[:10], 1):
        times_display = []
        for map_num in range(1, 6):
            if map_num in player['individual_times']:
                time_ms = player['individual_times'][map_num]
                time_str = format_time(time_ms)
                
                medal = ""
                if map_num in bot.competition.author_times:
                    if time_ms <= bot.competition.author_times[map_num]:
                        medal = "🏅"
                
                times_display.append(f"**{map_num}:** {time_str}{medal}")
            else:
                times_display.append(f"**{map_num}:** ❌")
        
        times_text = " | ".join(times_display)
        
        maps_done = player['maps_completed']
        author_medals = player['author_medals']
        medal_text = f" | 🏅{author_medals}" if author_medals > 0 else ""
        summary = f"📊 {maps_done}/5 maps{medal_text}"

        embed.add_field(
            name=f"#{i} - {player['tm_username']}",
            value=f"{times_text}\n{summary}",
            inline=False
        )

    await ctx.send(embed=embed)

@bot.command(name='map')
async def show_map_leaderboard(ctx, map_num: int):
    if map_num not in range(1, 6):
        await ctx.send("❌ Map number must be between 1 and 5!")
        return

    map_leaderboard = bot.competition.get_map_leaderboard(map_num)
    if not map_leaderboard:
        await ctx.send(f"📊 No times submitted for Map {map_num} yet!")
        return

    embed = discord.Embed(
        title=f"🗺️ Map {map_num} Leaderboard",
        description=bot.competition.week_maps[map_num],
        color=discord.Color.orange()
    )

    if map_num in bot.competition.author_times:
        author_time = format_time(bot.competition.author_times[map_num])
        embed.add_field(name="🏅 Author Medal", value=f"⏱️ {author_time}", inline=False)

    for i, player in enumerate(map_leaderboard[:10], 1):
        time_str = format_time(player['time'])
        
        if player['split'] is None:
            display_text = f"⏱️ {time_str}"
        else:
            split_str = format_time(player['split'])
            display_text = f"⏱️ {time_str} (+{split_str})"
        
        if map_num in bot.competition.author_times:
            if player['time'] <= bot.competition.author_times[map_num]:
                display_text += " 🏅"

        embed.add_field(
            name=f"#{i} - {player['tm_username']}",
            value=display_text,
            inline=False
        )

    await ctx.send(embed=embed)

def parse_time(time_str: str) -> Optional[int]:
    time_str = time_str.strip().replace(',', '.')

    match = re.match(r'^(\d+):(\d{1,2})[:.](\d{1,3})$', time_str)
    if match:
        minutes, seconds, ms = match.groups()
        ms = ms.ljust(3, '0')[:3]
        return int(minutes) * 60000 + int(seconds) * 1000 + int(ms)

    match = re.match(r'^(\d+)\.(\d{1,3})$', time_str)
    if match:
        seconds, ms = match.groups()
        ms = ms.ljust(3, '0')[:3]
        return int(seconds) * 1000 + int(ms)

    match = re.match(r'^(\d+)$', time_str)
    if match:
        return int(time_str)

    return None

def format_time(ms: int) -> str:
    if ms <= 0:
        return "00:00.000"

    minutes = ms // 60000
    seconds = (ms % 60000) // 1000
    milliseconds = ms % 1000

    return f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

if __name__ == "__main__":
    if not TOKEN:
        print("❌ Please set DISCORD_BOT_TOKEN environment variable")
        print(f"Current TOKEN value: {repr(TOKEN)}")
        exit(1)

    print("🚀 Starting Trackmania Weekly Shorts Bot...")
    bot.run(TOKEN)