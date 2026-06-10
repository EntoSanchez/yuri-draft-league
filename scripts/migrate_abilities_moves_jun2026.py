"""
One-time migration: abilities and moves for Megas and new Pokemon added June 2026.
Run: DB_PATH=/home/zcs55397/yuri-draft-league/yuri-draft-league/league.db python scripts/migrate_abilities_moves_jun2026.py
"""
import sqlite3, os

DB = os.environ.get("DB_PATH", "league.db")

ENTRIES = [
    ('Goodra', 'Sap Sipper', 'Hydration', 'Gooey', 'Acid Armor|Acid Spray|Body Press|Breaking Swipe|Bulldoze|Charm|Chilling Water|Curse|Dragon Cheer|Dragon Tail|Infestation|Knock Off|Life Dew|Muddy Water|Rain Dance|Sunny Day|Tera Blast|Toxic|Weather Ball|hail'),
    ('Golem', 'Rock Head', 'Sturdy', 'Sand Veil', 'Autotomize|Block|Body Press|Brick Break|Bulldoze|Curse|Hard Press|Iron Defense|Roar|Rock Polish|Sandstorm|Stealth Rock|Sucker Punch|Sunny Day|Tera Blast|Toxic|Wide Guard'),
    ('Jangmo O', 'Bulletproof', 'Soundproof', 'Overcoat', 'Breaking Swipe|Bulk Up|Bulldoze|Dragon Dance|Dragon Tail|Iron Defense|Roar|Sandstorm|Swords Dance|Taunt'),
    ('Hakamo O', 'Bulletproof', 'Soundproof', 'Overcoat', 'Breaking Swipe|Bulk Up|Bulldoze|Dragon Dance|Dragon Tail|Iron Defense|Roar|Sandstorm|Swords Dance|Taunt'),
    ('Kommo O', 'Bulletproof', 'Soundproof', 'Overcoat', 'Belly Drum|Body Press|Breaking Swipe|Bulk Up|Coaching|Dragon Cheer|Dragon Dance|Dragon Tail|Helping Hand|Iron Defense|Rain Dance|Roar|Sandstorm|Stealth Rock|Sunny Day|Swords Dance|Taunt|Tera Blast|Upper Hand|Vacuum Wave'),
    ('Flabebe', 'Flower Veil', '', 'Symbiosis', 'After You|Alluring Voice|Ally Switch|Aromatherapy|Baton Pass|Calm Mind|Charm|Chilling Water|Heal Bell|Helping Hand|Light Screen|Pollen Puff|Rain Dance|Stored Power|Sunny Day|Synthesis|Tera Blast|Toxic|Trailblaze|Wish'),
    ('Nidoran F', 'Poison Point', 'Rivalry', 'Hustle', ''),
    ('Nidoran M', 'Poison Point', 'Rivalry', 'Hustle', ''),
    ('Klawf', 'Anger Shell', 'Shell Armor', 'Regenerator', 'Block|Brick Break|Bulldoze|Helping Hand|Iron Defense|Knock Off|Rain Dance|Sandstorm|Stealth Rock|Sunny Day|Swords Dance|Temper Flare|Tera Blast|Trailblaze'),
    ('Type Null', 'Battle Armor', '', '', ''),
    ('Klink', 'Plus', 'Minus', 'Clear Body', 'Autotomize|Gravity|Iron Defense|Recycle|Rock Polish|Sandstorm|Screech|Shift Gear|Thunder Wave|Toxic|Volt Switch'),
    ('Mega Absol Z', 'Pressure', 'Super Luck', 'Justified', 'Baton Pass|Calm Mind|Curse|Foul Play|Hone Claws|Icy Wind|Knock Off|Mean Look|Pursuit|Quick Attack|Rain Dance|Sandstorm|Shadow Sneak|Snarl|Sucker Punch|Sunny Day|Swords Dance|Taunt|Thunder Wave|Toxic|Will-O-Wisp|Wish|hail'),
    ('Mega Barbaracle', 'Tough Claws', 'Sniper', 'Pickpocket', 'Beat up|Brick Break|Bulk Up|Bulldoze|Helping Hand|Hone Claws|Icy Wind|Infestation|Iron Defense|Muddy Water|Rain Dance|Rock Polish|Sandstorm|Screech|Shell Smash|Stealth Rock|Switcheroo|Swords Dance|Taunt|Toxic|Whirlpool'),
    ('Mega Baxcalibur', 'Thermal Exchange', '', 'Ice Body', 'Body Press|Breaking Swipe|Brick Break|Bulldoze|Dragon Cheer|Dragon Dance|Dragon Tail|Freeze-Dry|Helping Hand|Ice Shard|Icy Wind|Psychic Fangs|Rain Dance|Swords Dance|Tera Blast'),
    ('Mega Chandelure', 'Infiltrator', '', '', 'Acid Armor|Acid Spray|Ally Switch|Calm Mind|Clear Smog|Curse|Fire Spin|Haze|Heat Wave|Imprison|Memento|Minimize|Sunny Day|Taunt|Temper Flare|Tera Blast|Toxic|Trailblaze|Trick|Trick Room|Will-O-Wisp'),
    ('Mega Chesnaught', 'Bulletproof', '', '', 'Belly Drum|Block|Body Press|Brick Break|Bulk Up|Bulldoze|Coaching|Curse|Grassy Glide|Helping Hand|Hone Claws|Iron Defense|Knock Off|Quick Guard|Rain Dance|Reflect|Roar|Spikes|Sunny Day|Super Fang|Swords Dance|Synthesis|Taunt|Tera Blast|Toxic|Trailblaze|Wide Guard'),
    ('Mega Chimecho', 'Levitate', '', '', 'Ally Switch|Amnesia|Baton Pass|Calm Mind|Charm|Cosmic Power|Curse|Defog|Encore|Fake Tears|Gravity|Heal Bell|Heal Pulse|Healing Wish|Helping Hand|Icy Wind|Imprison|Knock Off|Light Screen|Psychic Noise|Rain Dance|Recover|Recycle|Reflect|Screech|Snarl|Stored Power|Sunny Day|Taunt|Tera Blast|Thunder Wave|Toxic|Trick|Trick Room|Wish'),
    ('Mega Clefable', 'Magic Bounce', '', '', 'After You|Alluring Voice|Ally Switch|Amnesia|Aromatherapy|Baton Pass|Belly Drum|Brick Break|Calm Mind|Charm|Chilling Water|Cosmic Power|Curse|Encore|Fake Tears|Follow me|Gravity|Heal Bell|Heal Pulse|Healing Wish|Helping Hand|Icy Wind|Imprison|Knock Off|Life Dew|Light Screen|Minimize|Moonlight|Rain Dance|Recycle|Reflect|Soft Boiled|Stealth Rock|Stored Power|Sunny Day|Teleport|Tera Blast|Thunder Wave|Toxic|Trick|Wish'),
    ('Mega Crabominable', 'Iron Fist', '', '', 'Amnesia|Block|Body Press|Brick Break|Bulk Up|Bulldoze|Chilling Water|Coaching|First Impression|Hard Press|Helping Hand|Ice Spinner|Icy Wind|Iron Defense|Knock Off|Mach Punch|Pursuit|Rain Dance|Sunny Day|Taunt|Tera Blast|Toxic|Upper Hand|Wide Guard|hail'),
    ('Mega Darkrai', 'Bad Dreams', '', '', 'Brick Break|Calm Mind|Curse|Foul Play|Haze|Icy Wind|Knock Off|Nasty Plot|Pursuit|Quick Attack|Rain Dance|Shadow Sneak|Snarl|Sucker Punch|Sunny Day|Swords Dance|Taunt|Tera Blast|Thunder Wave|Toxic|Trick|Vacuum Wave|Will-O-Wisp'),
    ('Mega Delphox', 'Levitate', '', '', 'Agility|Ally Switch|Calm Mind|Charm|Encore|Fire Spin|Foul Play|Heat Wave|Helping Hand|Howl|Imprison|Light Screen|Nasty Plot|Psychic Noise|Rain Dance|Recycle|Reflect|Stored Power|Sunny Day|Switcheroo|Tera Blast|Toxic|Trick|Trick Room|Will-O-Wisp|Wish'),
    ('Mega Dragalge', 'Poison Point', 'Poison Touch', 'Adaptability', 'Acid Armor|Acid Spray|Chilling Water|Dragon Tail|Flip Turn|Haze|Icy Wind|Muddy Water|Rain Dance|Tera Blast|Toxic|Toxic Spikes|Whirlpool|hail'),
    ('Mega Dragonite', 'Multiscale', '', '', 'Agility|Aqua Jet|Body Press|Breaking Swipe|Brick Break|Bulldoze|Chilling Water|Curse|Defog|Dragon Cheer|Dragon Dance|Dragon Tail|Encore|Extreme Speed|Fire Spin|Haze|Heal Bell|Heat Wave|Helping Hand|Hone Claws|Ice Spinner|Icy Wind|Light Screen|Rain Dance|Reflect|Roar|Roost|Sandstorm|Sunny Day|Tailwind|Tera Blast|Thunder Wave|Toxic|Vacuum Wave|Weather Ball|Whirlpool|Whirlwind|hail'),
    ('Mega Drampa', 'Berserk', '', '', 'Amnesia|Block|Breaking Swipe|Bulldoze|Calm Mind|Defog|Dragon Dance|Dragon Tail|Glare|Heat Wave|Helping Hand|Icy Wind|Light Screen|Rain Dance|Roar|Roost|Snarl|Sunny Day|Tailwind|Thunder Wave|Toxic|Whirlwind'),
    ('Mega Eelektross', 'Levitate', '', '', 'Acid Spray|Body Press|Brick Break|Bulk Up|Bulldoze|Coil|Dragon Tail|Eerie Impulse|Electro Web|Hone Claws|Knock Off|Light Screen|Muddy Water|Psychic Fangs|Rain Dance|Roar|Sunny Day|Super Fang|Supercell Slam|Tera Blast|Thunder Wave|Toxic|U-Turn|Volt Switch'),
    ('Mega Emboar', 'Mold Breaker', '', '', 'Block|Body Press|Brick Break|Bulk Up|Bulldoze|Circle Throw|Coaching|Curse|Fire Spin|Hard Press|Heat Wave|Helping Hand|Knock Off|Roar|Sucker Punch|Sunny Day|Taunt|Temper Flare|Tera Blast|Toxic|Trailblaze|Vacuum Wave|Will-O-Wisp'),
    ('Mega Excadrill', 'Piercing Drill', '', '', 'Agility|Brick Break|Bulldoze|Curse|Helping Hand|Hone Claws|Iron Defense|Rapid Spin|Sand Tomb|Sandstorm|Stealth Rock|Sunny Day|Swords Dance|Tera Blast|Toxic'),
    ('Mega Falinks', 'Battle Armor', '', 'Defiant', 'Agility|Beat up|Body Press|Brick Break|Bulk Up|Coaching|Fake out|First Impression|Helping Hand|Iron Defense|Knock Off|Rain Dance|Screech|Sunny Day|Swords Dance|Tera Blast|Trailblaze|Upper Hand'),
    ('Mega Feraligatr', 'Dragonize', '', '', 'Agility|Aqua Jet|Block|Breaking Swipe|Brick Break|Bulldoze|Chilling Water|Curse|Dragon Dance|Dragon Tail|Fake Tears|Flip Turn|Helping Hand|Hone Claws|Icy Wind|Muddy Water|Psychic Fangs|Rain Dance|Roar|Screech|Snarl|Swords Dance|Tera Blast|Toxic|Trailblaze|Whirlpool|hail'),
    ('Mega Floette', 'Fairy Aura', '', '', 'After You|Alluring Voice|Ally Switch|Aromatherapy|Baton Pass|Calm Mind|Charm|Chilling Water|Heal Bell|Helping Hand|Light Screen|Pollen Puff|Rain Dance|Stored Power|Sunny Day|Synthesis|Tera Blast|Toxic|Trailblaze|Trick|Wish'),
    ('Mega Froslass', 'Snow Warning', '', '', 'Ally Switch|Aurora Veil|Block|Charm|Chilling Water|Curse|Fake Tears|Haze|Helping Hand|Ice Shard|Ice Spinner|Icy Wind|Imprison|Light Screen|Nasty Plot|Rain Dance|Reflect|Spikes|Sucker Punch|Switcheroo|Taunt|Tera Blast|Thunder Wave|Toxic|Trailblaze|Trick|Weather Ball|Will-O-Wisp|hail'),
    ('Mega Garchomp Z', 'Sand Veil', '', 'Rough Skin', 'Breaking Swipe|Brick Break|Bulldoze|Dragon Cheer|Dragon Tail|Helping Hand|Hone Claws|Nasty Plot|Rain Dance|Roar|Sand Tomb|Sandstorm|Spikes|Stealth Rock|Sunny Day|Swords Dance|Tera Blast|Toxic|Vacuum Wave|Whirlpool'),
    ('Mega Glimmora', 'Adaptability', '', '', 'Acid Armor|Acid Spray|Iron Defense|Light Screen|Memento|Other Removal|Rain Dance|Reflect|Rock Polish|Sand Tomb|Sandstorm|Spikes|Stealth Rock|Sunny Day|Tera Blast|Toxic|Toxic Spikes'),
    ('Mega Golisopod', 'Emergency Exit', '', '', 'Agility|Aqua Jet|Brick Break|Bulk Up|First Impression|Icy Wind|Iron Defense|Knock Off|Muddy Water|Other Momentum|Rain Dance|Screech|Snarl|Spikes|Sucker Punch|Swords Dance|Taunt|Toxic|U-Turn|Wide Guard|hail'),
    ('Mega Golurk', 'Unseen Fist', '', '', 'Ally Switch|Block|Body Press|Brick Break|Bulldoze|Curse|Gravity|Hard Press|Helping Hand|Icy Wind|Imprison|Iron Defense|Knock Off|Rain Dance|Reflect|Rock Polish|Sandstorm|Stealth Rock|Sunny Day|Tera Blast|Toxic|Trick'),
    ('Mega Greninja', 'Protean', '', '', 'Brick Break|Chilling Water|Flip Turn|Haze|Helping Hand|Icy Wind|Nasty Plot|Quick Attack|Rain Dance|Shadow Sneak|Spikes|Switcheroo|Swords Dance|Taunt|Tera Blast|Toxic|Toxic Spikes|Trailblaze|U-Turn|Upper Hand|Vacuum Wave|Weather Ball'),
    ('Mega Hawlucha', 'Limber', 'Unburden', 'Mold Breaker', 'Agility|Ally Switch|Baton Pass|Body Press|Brick Break|Bulk Up|Coaching|Defog|Encore|Helping Hand|Hone Claws|Mean Look|Quick Guard|Rain Dance|Roost|Sunny Day|Swords Dance|Tailwind|Taunt|Tera Blast|Toxic|Trailblaze|U-Turn|Upper Hand'),
    ('Mega Heatran', 'Flash Fire', '', 'Flame Body', 'Body Press|Bulldoze|Fire Spin|First Impression|Hard Press|Heat Wave|Iron Defense|Roar|Sandstorm|Stealth Rock|Sunny Day|Taunt|Tera Blast|Toxic|Will-O-Wisp'),
    ('Mega Lucario Z', 'Steadfast', 'Inner Focus', 'Justified', 'Agility|Brick Break|Bulk Up|Bulldoze|Bullet Punch|Calm Mind|Circle Throw|Coaching|Extreme Speed|Follow me|Heal Pulse|Helping Hand|Hone Claws|Howl|Iron Defense|Life Dew|Nasty Plot|Quick Attack|Quick Guard|Rain Dance|Roar|Screech|Sunny Day|Swords Dance|Tera Blast|Toxic|Trailblaze|Upper Hand|Vacuum Wave'),
    ('Mega Magearna', 'Soul Heart', '', '', 'After You|Agility|Baton Pass|Brick Break|Calm Mind|Eerie Impulse|Electro Web|Encore|Gravity|Heal Bell|Helping Hand|Ice Spinner|Imprison|Iron Defense|Light Screen|Reflect|Shift Gear|Spikes|Stored Power|Sunny Day|Tera Blast|Thunder Wave|Trick|Trick Room|Vacuum Wave|Volt Switch'),
    ('Mega Magearna Original', 'Soul Heart', '', '', 'After You|Agility|Baton Pass|Brick Break|Calm Mind|Eerie Impulse|Electro Web|Encore|Gravity|Heal Bell|Helping Hand|Ice Spinner|Imprison|Iron Defense|Light Screen|Reflect|Shift Gear|Spikes|Stored Power|Sunny Day|Tera Blast|Thunder Wave|Trick|Trick Room|Vacuum Wave|Volt Switch'),
    ('Mega Malamar', 'Contrary', 'Suction Cups', 'Infiltrator', 'Ally Switch|Baton Pass|Block|Bulk Up|Calm Mind|Circle Throw|Fake Tears|Foul Play|Gravity|Helping Hand|Knock Off|Light Screen|Nasty Plot|Psychic Noise|Rain Dance|Reflect|Stealth Rock|Stored Power|Sunny Day|Switcheroo|Taunt|Tera Blast|Toxic|Trailblaze|Trick|Trick Room'),
    ('Mega Meganium', 'Mega Sol', '', '', 'Aromatherapy|Body Press|Bulldoze|Charm|Curse|Dragon Tail|Encore|Fake Tears|Grassy Glide|Heal Pulse|Helping Hand|Knock Off|Light Screen|Reflect|Sunny Day|Swords Dance|Synthesis|Tera Blast|Toxic|Trailblaze|Weather Ball'),
    ('Mega Meowstic', 'Trace', '', '', 'Alluring Voice|Ally Switch|Baton Pass|Calm Mind|Charm|Fake Tears|Fake out|Gravity|Heal Bell|Helping Hand|Imprison|Light Screen|Mean Look|Nasty Plot|Psychic Noise|Quick Guard|Rain Dance|Recycle|Reflect|Spikes|Stealth Rock|Stored Power|Sucker Punch|Sunny Day|Taunt|Teleport|Tera Blast|Thunder Wave|Toxic|Toxic Spikes|Trailblaze|Trick|Trick Room|Wish'),
    ('Mega Pyroar', 'Rivalry', 'Unnerve', 'Moxie', 'Bulldoze|Fire Spin|Heat Wave|Helping Hand|Psychic Fangs|Rain Dance|Roar|Snarl|Sunny Day|Taunt|Temper Flare|Tera Blast|Toxic|Trailblaze|Will-O-Wisp'),
    ('Mega Raichu X', 'Static', '', 'Lightning Rod', 'Agility|Alluring Voice|Brick Break|Calm Mind|Charm|Curse|Eerie Impulse|Electro Web|Encore|Extreme Speed|Fake Tears|Fake out|Follow me|Helping Hand|Knock Off|Light Screen|Nasty Plot|Quick Attack|Rain Dance|Reflect|Tera Blast|Thunder Wave|Toxic|Trailblaze|Upper Hand|Volt Switch|Wish'),
    ('Mega Raichu Y', 'Static', '', 'Lightning Rod', 'Agility|Alluring Voice|Brick Break|Calm Mind|Charm|Curse|Eerie Impulse|Electro Web|Encore|Extreme Speed|Fake Tears|Fake out|Follow me|Helping Hand|Knock Off|Light Screen|Nasty Plot|Quick Attack|Rain Dance|Reflect|Tera Blast|Thunder Wave|Toxic|Trailblaze|Upper Hand|Volt Switch|Wish'),
    ('Mega Scolipede', 'Poison Point', 'Swarm', 'Speed Boost', 'Acid Spray|Agility|Baton Pass|Bulldoze|First Impression|Infestation|Iron Defense|Other Removal|Pursuit|Screech|Spikes|Sunny Day|Swords Dance|Toxic|Toxic Spikes|Trailblaze|U-Turn'),
    ('Mega Scovillain', 'Spicy Spray', '', '', 'Fire Spin|Grassy Glide|Helping Hand|Nasty Plot|Rage Powder|Sandstorm|Sunny Day|Super Fang|Temper Flare|Tera Blast|Trailblaze|Will-O-Wisp'),
    ('Mega Scrafty', 'Shed Skin', 'Moxie', 'Intimidate', 'Acid Spray|Amnesia|Beat up|Brick Break|Bulk Up|Coaching|Curse|Dragon Dance|Dragon Tail|Encore|Fake Tears|Fake out|Foul Play|Helping Hand|Iron Defense|Knock Off|Parting Shot|Quick Guard|Rain Dance|Roar|Snarl|Sunny Day|Super Fang|Swords Dance|Taunt|Tera Blast|Toxic|Trailblaze|Upper Hand'),
    ('Mega Skarmory', 'Stalwart', '', '', 'Agility|Autotomize|Body Press|Curse|Defog|Icy Wind|Iron Defense|Pursuit|Roar|Roost|Sand Tomb|Sandstorm|Spikes|Stealth Rock|Sunny Day|Swords Dance|Tailwind|Taunt|Tera Blast|Toxic|Whirlwind'),
    ('Mega Staraptor', 'Intimidate', '', 'Reckless', 'Agility|Brick Break|Bulk Up|Defog|Heat Wave|Helping Hand|Knock Off|Pursuit|Quick Attack|Rain Dance|Roost|Sunny Day|Tailwind|Tera Blast|Toxic|U-Turn|Vacuum Wave|Whirlwind'),
    ('Mega Starmie', 'Huge Power', '', '', 'Agility|Ally Switch|Aqua Jet|Bulk Up|Chilling Water|Cosmic Power|Curse|Flip Turn|Gravity|Icy Wind|Light Screen|Minimize|Rain Dance|Rapid Spin|Recover|Recycle|Reflect|Teleport|Thunder Wave|Toxic|Trick|Trick Room|Whirlpool|hail'),
    ('Mega Tatsugiri Curly', 'Commander', '', 'Storm Drain', 'Baton Pass|Calm Mind|Chilling Water|Dragon Cheer|Dragon Dance|Flip Turn|Helping Hand|Icy Wind|Memento|Muddy Water|Nasty Plot|Rain Dance|Rapid Spin|Taunt|Tera Blast|Whirlpool'),
    ('Mega Tatsugiri Droopy', 'Commander', '', 'Storm Drain', 'Baton Pass|Calm Mind|Chilling Water|Dragon Cheer|Dragon Dance|Flip Turn|Helping Hand|Icy Wind|Memento|Muddy Water|Nasty Plot|Rain Dance|Rapid Spin|Taunt|Tera Blast|Whirlpool'),
    ('Mega Tatsugiri Stretchy', 'Commander', '', 'Storm Drain', 'Baton Pass|Calm Mind|Chilling Water|Dragon Cheer|Dragon Dance|Flip Turn|Helping Hand|Icy Wind|Memento|Muddy Water|Nasty Plot|Rain Dance|Rapid Spin|Taunt|Tera Blast|Whirlpool'),
    ('Mega Victreebel', 'Innards Out', '', '', 'Acid Spray|Clear Smog|Curse|Encore|Grassy Glide|Infestation|Knock Off|Morning Sun|Reflect|Sleep Powder|Stockpile|Strength Sap|Stun Spore|Sucker Punch|Sunny Day|Swords Dance|Synthesis|Tera Blast|Toxic|Toxic Spikes|Trailblaze|Weather Ball'),
    ('Mega Zeraora', 'Volt Absorb', '', '', 'Agility|Brick Break|Bulk Up|Calm Mind|Coaching|Electro Web|Fake out|Helping Hand|Hone Claws|Knock Off|Quick Attack|Quick Guard|Snarl|Taunt|Thunder Wave|Toxic|Vacuum Wave|Volt Switch'),
    ('Mega Zygarde', 'Aura Break', '', '', 'Block|Breaking Swipe|Brick Break|Bulldoze|Coil|Dragon Dance|Dragon Tail|Extreme Speed|Glare|Haze|Psychic Fangs|Sandstorm|Sunny Day|Toxic'),
    ('Zygarde 10%', 'Aura Break', '', '', 'Block|Breaking Swipe|Brick Break|Bulldoze|Coil|Dragon Dance|Dragon Tail|Extreme Speed|Glare|Haze|Psychic Fangs|Sandstorm|Sunny Day|Toxic'),
    ('Zygarde', 'Aura Break', '', '', 'Block|Brick Break|Coil|Dragon Dance|Dragon Tail|Extreme Speed|Glare|Haze|Sandstorm|Sunny Day|Toxic'),
    ('Calyrex-Ice-Rider', 'As One Glastrier', '', '', 'Agility|Baton Pass|Body Press|Calm Mind|Gravity|Helping Hand|Imprison|Iron Defense|Light Screen|Reflect|Snarl|Stored Power|Sunny Day|Swords Dance|Taunt|Trick|Trick Room'),
    ('Paldean Tauros', 'Intimidate', 'Anger Point', 'Cud Chew', 'Bulldoze|Curse|Helping Hand|Icy Wind|Rain Dance|Sandstorm|Sunny Day|Tera Blast|Trailblaze'),
]

def main():
    db = sqlite3.connect(DB)
    c = db.cursor()
    updated = 0
    for name, ab1, ab2, ab3, moves in ENTRIES:
        c.execute(
            "UPDATE draft_tiers SET ability1=?, ability2=?, ability3=?, moves=? WHERE name=?",
            (ab1, ab2, ab3, moves, name)
        )
        updated += c.rowcount
    db.commit()
    print(f"Done. Updated {updated} rows.")
    db.close()

if __name__ == "__main__":
    main()
