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
GUILD_ID = int(os.getenv('GUILD_ID', '0'))  # Your server ID
LEADERBOARD_CHANNEL = int(os.getenv('LEADERBOARD_CHANNEL', '0'))  # Channel for daily updates

class WeeklyCompetition:
    """Manages weekly competition data"""

    def __init__(self):
        self.data_file = "competition_data.json"
        self.current_week = self.get_current_week()
        self.player_times = {}  # {discord_id: {map_num: time_ms, ...}}
        self.player_names = {}  # {discord_id: tm_username}
        self.author_times = {}  # {map_num: time_ms}
        self.week_maps = {
            1: "Map 1 - Short Track Alpha",
            2: "Map 2 - Short Track Beta", 
            3: "Map 3 - Short Track Gamma",
            4: "Map 4 - Short Track Delta",
            5: "Map 5 - Short Track Epsilon"
        }
        self.load_data()

    def load_data(self):
        """Load data from JSON file"""
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                
                # Load player names (these persist forever)
                self.player_names = {int(k): v for k, v in data.get('player_names', {}).items()}
                
                # Load current week data
                saved_week = data.get('current_week', '')
                if saved_week == self.current_week:
                    # Same week, load everything
                    self.player_times = {int(k): {int(map_k): map_v for map_k, map_v in v.items()} 
                                       for k, v in data.get('player_times', {}).items()}
                    self.author_times = {int(k): v for k, v in data.get('author_times', {}).items()}
                    print(f"📊 Loaded existing data for week {self.current_week}")
                else:
                    # New week, reset times but keep player names
                    self.player_times = {}
                    self.author_times = {}
                    print(f"🆕 New week detected! Reset times, kept {len(self.player_names)} registered players")
                    self.save_data()  # Save the reset state
            else:
                print("📝 No existing data file found, starting fresh")
        except Exception as e:
            print(f"⚠️ Error loading data: {e}")
            print("Starting with fresh data")

    def save_data(self):
        """Save data to JSON file"""
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
        """Get current week identifier (Year-Week)"""
        now = datetime.now()
        year = now.year
        # Week starts on Sunday for Trackmania
        week = now.isocalendar()[1]
        return f"{year}-W{week:02d}"

    def register_player(self, discord_id: int, tm_username: str):
        """Register a player's Trackmania username"""
        self.player_names[discord_id] = tm_username
        if discord_id not in self.player_times:
            self.player_times[discord_id] = {}
        self.save_data()  # Save after registration

    def add_time(self, discord_id: int, map_num: int, time_ms: int) -> bool:
        """Add or update a player's time for a specific map"""
        if discord_id not in self.player_names:
            return False  # Player not registered

        if map_num not in range(1, 6):
            return False  # Invalid map number

        if discord_id not in self.player_times:
            self.player_times[discord_id] = {}

        self.player_times[discord_id][map_num] = time_ms
        self.save_data()  # Save after time submission
        return True

    def set_author_time(self, map_num: int, time_ms: int) -> bool:
        """Set author time for a specific map"""
        if map_num not in range(1, 6):
            return False
        
        self.author_times[map_num] = time_ms
        self.save_data()  # Save after setting author time
        return True

    def get_map_leaderboard(self, map_num: int) -> List[Dict]:
        """Get leaderboard for a specific map with splits"""
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

        # Sort by time (fastest first)
        sorted_players = sorted(players, key=lambda x: x['time'])
        
        # Add splits relative to first place
        if sorted_players:
            first_time = sorted_players[0]['time']
            for player in sorted_players:
                if player['time'] == first_time:
                    player['split'] = None  # First place gets no split
                else:
                    player['split'] = player['time'] - first_time

        return sorted_players

    def get_overall_leaderboard(self) -> List[Dict]:
        """Get overall leaderboard showing all map times for each player"""
        players = []

        for discord_id in self.player_times:
            times = self.player_times[discord_id]
            if not times:  # Skip players with no times
                continue

            # Count author medals
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

        # Sort by maps completed (more maps = better), then by author medals, then by username
        return sorted(players, key=lambda x: (-x['maps_completed'], -x['author_medals'], x['tm_username'].lower()))

    def reset_week(self):
        """Reset for new week"""
        old_week = self.current_week
        self.current_week = self.get_current_week()
        self.player_times = {}
        self.author_times = {}  # Reset author times too
        # Keep player_names registered
        self.save_data()  # Save the reset state
        print(f"🔄 Week reset from {old_week} to {self.current_week}")
        print(f"📝 Kept {len(self.player_names)} registered players")

class WeeklyShortsBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!tm ', intents=intents)

        self.competition = WeeklyCompetition()

    async def setup_hook(self):
        """Called when bot starts"""
        self.weekly_reset_check.start()
        print("🏁 Trackmania Weekly Shorts Bot is ready!")
        print(f"📅 Current competition week: {self.competition.current_week}")

    async def close(self):
        """Cleanup when bot shuts down"""
        self.weekly_reset_check.cancel()
        await super().close()

    @tasks.loop(hours=1)  # Check every hour for week rollover
    async def weekly_reset_check(self):
        """Check if we need to reset for a new week"""
        current_week = self.competition.get_current_week()
        if current_week != self.competition.current_week:
            # New week started!
            await self.handle_week_reset(current_week)

    async def handle_week_reset(self, new_week: str):
        """Handle transition to new week"""
        channel = self.get_channel(LEADERBOARD_CHANNEL)
        if channel:
            # Post final results for previous week
            old_week = self.competition.current_week

            # Show final standings for each map
            for map_num in range(1, 6):
                map_leaderboard = self.competition.get_map_leaderboard(map_num)
                if map_leaderboard:
                    embed = discord.Embed(
                        title=f"🏁 Final Results - Week {old_week} - Map {map_num}",
                        description=self.competition.week_maps[map_num],
                        color=discord.Color.gold()
                    )

                    for i, player in enumerate(map_leaderboard[:5], 1):  # Top 5
                        time_str = format_time(player['time'])
                        
                        if player['split'] is None:
                            split_str = ""
                        else:
                            split_str = f" (+{format_time(player['split'])})"

                        embed.add_field(
                            name=f"{get_rank_emoji(i)} #{i} - {player['tm_username']}",
                            value=f"⏱️ {time_str}{split_str}",
                            inline=False
                        )

                    # Show author medal if set
                    if map_num in self.competition.author_times:
                        author_time = format_time(self.competition.author_times[map_num])
                        embed.add_field(
                            name="🏅 Author Medal",
                            value=f"⏱️ {author_time}",
                            inline=False
                        )

                    await channel.send(embed=embed)

            # Reset for new week
            self.competition.reset_week()

            # Announce new week
            embed = discord.Embed(
                title=f"🆕 New Week Started - {new_week}",
                description="Time for new Weekly Shorts! Register and submit your times.",
                color=discord.Color.blue()
            )
            await channel.send(embed=embed)

# Create bot instance
bot = WeeklyShortsBot()

@bot.event
async def on_ready():
    print(f'Bot logged in as {bot.user}!')
    print(f'Connected to {len(bot.guilds)} servers')

@bot.command(name='register')
async def register_player(ctx, *, trackmania_username: str):
    """Register your Trackmania username"""
    if len(trackmania_username) > 50:  # Reasonable limit
        await ctx.send("❌ Username too long! Please use a shorter name.")
        return

    bot.competition.register_player(ctx.author.id, trackmania_username)
    await ctx.send(f"✅ Registered `{trackmania_username}` for {ctx.author.mention}!")

@bot.command(name='time', aliases=['submit', 't'])
async def submit_time(ctx, map_num: int, *, time_str: str):
    """Submit your time for a map

    Usage: !tm time 1 1:23.456
    Formats accepted: 1:23.456, 83.456, 1:23:456, 83456 (ms)
    """

    # Check if player is registered
    if ctx.author.id not in bot.competition.player_names:
        await ctx.send("❌ Please register first with `!tm register <your_trackmania_username>`")
        return

    # Validate map number
    if map_num not in range(1, 6):
        await ctx.send("❌ Map number must be between 1 and 5!")
        return

    # Parse time
    time_ms = parse_time(time_str)
    if time_ms is None:
        await ctx.send("❌ Invalid time format! Use formats like: `1:23.456`, `83.456`, or `83456` (ms)")
        return

    # Check for reasonable time (between 1 second and 10 minutes)
    if not (1000 <= time_ms <= 600000):
        await ctx.send("❌ Time seems unreasonable (must be between 1 second and 10 minutes)")
        return

    # Submit the time
    success = bot.competition.add_time(ctx.author.id, map_num, time_ms)
    if success:
        formatted_time = format_time(time_ms)
        tm_username = bot.competition.player_names[ctx.author.id]

        embed = discord.Embed(
            title="⏱️ Time Submitted!",
            color=discord.Color.green()
        )
        embed.add_field(name="Player", value=tm_username, inline=True)
        embed.add_field(name="Map", value=f"#{map_num}", inline=True)
        embed.add_field(name="Time", value=formatted_time, inline=True)

        # Check if they beat author time
        if map_num in bot.competition.author_times:
            author_time = bot.competition.author_times[map_num]
            if time_ms <= author_time:
                embed.add_field(name="🏅", value="Author Medal!", inline=True)

        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ Failed to submit time. Please try again.")

@bot.command(name='author')
@commands.has_permissions(administrator=True)
async def set_author_time(ctx, map_num: int, *, time_str: str):
    """Set author time for a map (Admin only)

    Usage: !tm author 1 1:20.500
    """
    # Validate map number
    if map_num not in range(1, 6):
        await ctx.send("❌ Map number must be between 1 and 5!")
        return

    # Parse time
    time_ms = parse_time(time_str)
    if time_ms is None:
        await ctx.send("❌ Invalid time format! Use formats like: `1:23.456`, `83.456`, or `83456` (ms)")
        return

    # Check for reasonable time
    if not (1000 <= time_ms <= 600000):
        await ctx.send("❌ Time seems unreasonable (must be between 1 second and 10 minutes)")
        return

    # Set author time
    success = bot.competition.set_author_time(map_num, time_ms)
    if success:
        formatted_time = format_time(time_ms)
        embed = discord.Embed(
            title="🏅 Author Time Set!",
            color=discord.Color.gold()
        )
        embed.add_field(name="Map", value=f"#{map_num}", inline=True)
        embed.add_field(name="Author Time", value=formatted_time, inline=True)
        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ Failed to set author time.")

@bot.command(name='times', aliases=['mytimes'])
async def show_my_times(ctx):
    """Show your submitted times"""
    if ctx.author.id not in bot.competition.player_names:
        await ctx.send("❌ Please register first with `!tm register <your_trackmania_username>`")
        return

    times = bot.competition.player_times.get(ctx.author.id, {})
    tm_username = bot.competition.player_names[ctx.author.id]

    embed = discord.Embed(
        title=f"📊 Times for {tm_username}",
        color=discord.Color.blue()
    )

    if not times:
        embed.description = "No times submitted yet!"
    else:
        embed.add_field(
            name="📈 Progress",
            value=f"**Maps Completed**: {len(times)}/5",
            inline=False
        )

        for map_num in range(1, 6):
            if map_num in times:
                time_str = format_time(times[map_num])
                
                # Check for author medal
                medal_text = ""
                if map_num in bot.competition.author_times:
                    if times[map_num] <= bot.competition.author_times[map_num]:
                        medal_text = " 🏅"
                
                embed.add_field(name=f"Map {map_num}", value=f"{time_str}{medal_text}", inline=True)
            else:
                embed.add_field(name=f"Map {map_num}", value="❌ Not done", inline=True)

    await ctx.send(embed=embed)

@bot.command(name='leaderboard', aliases=['lb', 'standings'])
async def show_leaderboard(ctx):
    """Show current weekly leaderboard with all map times"""
    leaderboard = bot.competition.get_overall_leaderboard()

    if not leaderboard:
        await ctx.send("📊 No times submitted yet this week!")
        return

    embed = discord.Embed(
        title=f"🏁 Weekly Shorts Leaderboard - {bot.competition.current_week}",
        description="All player times across the 5 maps",
        color=discord.Color.green()
    )

    for i, player in enumerate(leaderboard[:10], 1):  # Top 10 players
        # Build the times display for all 5 maps
        times_display = []
        for map_num in range(1, 6):
            if map_num in player['individual_times']:
                time_ms = player['individual_times'][map_num]
                time_str = format_time(time_ms)
                
                # Check for author medal
                medal = ""
                if map_num in bot.competition.author_times:
                    if time_ms <= bot.competition.author_times[map_num]:
                        medal = "🏅"
                
                times_display.append(f"**{map_num}:** {time_str}{medal}")
            else:
                times_display.append(f"**{map_num}:** ❌")
        
        times_text = " | ".join(times_display)
        
        # Summary line
        maps_done = player['maps_completed']
        author_medals = player['author_medals']
        medal_text = f" | 🏅{author_medals}" if author_medals > 0 else ""
        summary = f"📊 {maps_done}/5 maps{medal_text}"

        embed.add_field(
            name=f"{get_rank_emoji(i)} #{i} - {player['tm_username']}",
            value=f"{times_text}\n{summary}",
            inline=False
        )

    embed.set_footer(text=f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC")
    await ctx.send(embed=embed)

@bot.command(name='map', aliases=['mapboard'])
async def show_map_leaderboard(ctx, map_num: int):
    """Show leaderboard for a specific map"""
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

    # Show author time if set
    if map_num in bot.competition.author_times:
        author_time = format_time(bot.competition.author_times[map_num])
        embed.add_field(
            name="🏅 Author Medal",
            value=f"⏱️ {author_time}",
            inline=False
        )

    for i, player in enumerate(map_leaderboard[:10], 1):  # Top 10
        time_str = format_time(player['time'])
        
        if player['split'] is None:
            # First place
            display_text = f"⏱️ {time_str}"
        else:
            # Show split
            split_str = format_time(player['split'])
            display_text = f"⏱️ {time_str} (+{split_str})"
        
        # Check for author medal
        if map_num in bot.competition.author_times:
            if player['time'] <= bot.competition.author_times[map_num]:
                display_text += " 🏅"

        embed.add_field(
            name=f"{get_rank_emoji(i)} #{i} - {player['tm_username']}",
            value=display_text,
            inline=False
        )

    await ctx.send(embed=embed)

@bot.command(name='week', aliases=['info'])
async def show_week_info(ctx):
    """Show current week information"""
    embed = discord.Embed(
        title=f"📅 Weekly Shorts - {bot.competition.current_week}",
        description="Submit your times for all 5 maps!",
        color=discord.Color.blue()
    )

    for map_num, map_name in bot.competition.week_maps.items():
        submitted_count = len(bot.competition.get_map_leaderboard(map_num))
        
        # Show author time if set
        author_text = ""
        if map_num in bot.competition.