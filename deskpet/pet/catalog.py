"""The desktop shop's local catalogue. Prices are in earned music notes."""
from dataclasses import dataclass

from deskpet.paths import RESOURCE_ROOT


@dataclass(frozen=True)
class ShopItem:
    key: str
    name: str
    category: str
    price: int
    description: str
    fullness: int = 0
    mood: int = 0
    xp: int = 0
    animated: bool = False
    panoramic: bool = False

    @property
    def image(self):
        return RESOURCE_ROOT / 'assets' / 'ui' / 'shop' / (self.key + '.webp')

    @property
    def panorama_image(self):
        return self.image.parent / 'panoramas' / self.image.name


CATEGORIES = {'food': '食物', 'gift': '小礼物', 'accessory': '装扮', 'background': '桌宠背景'}
ITEMS = {item.key: item for item in (
    ShopItem('bao', '小包子', 'food', 8, '一口掰开，热气从白软的褶子里冒出来。', 15, 3, 3),
    ShopItem('dumplings', '小笼包', 'food', 15, '揭开竹盖，一笼汤汁满满的小笼包。', 30, 6, 6),
    ShopItem('osmanthus', '桂花糕', 'food', 12, '桂花撒在米糕上，指尖也沾了一点甜。', 15, 10, 4),
    ShopItem('riceball', '海苔饭团', 'food', 10, '用海苔裹紧米饭，排练间隙也能捧着吃。', 22, 2, 4),
    ShopItem('noodles', '葱香汤面', 'food', 20, '青花碗盛着热汤、细面和一把碧绿葱花。', 40, 5, 7),
    ShopItem('peach', '蜜桃酸奶', 'food', 14, '切好的蜜桃浸在酸奶里，冰冰凉凉。', 18, 12, 4),
    ShopItem('pinwheel', '纸风车', 'gift', 6, '轻轻吹一口气，四色小风车就转起来了。', mood=6),
    ShopItem('musicbox', '星星八音盒', 'gift', 18, '转动发条，把一段旋律送给天依。', mood=18),
    ShopItem('sunflowers', '向日葵小花束', 'gift', 12, '三朵小太阳，用牛皮纸仔细包好。', mood=12),
    ShopItem('bow', '晴空蝴蝶结', 'accessory', 30, '把浅蓝缎带别在发间，陪天依一起出门。'),
    ShopItem('stars', '双星发夹', 'accessory', 45, '两颗小金星，沿着刘海排成一列。'),
    ShopItem('daisy', '雏菊发卡', 'accessory', 35, '一朵白雏菊，花瓣旁探出两片嫩叶。'),
    ShopItem('picnic', '薄荷格坐垫', 'background', 0, '天依自带的小坐垫，边角缀着一朵雏菊。'),
    ShopItem('garden', '午后花庭', 'background', 50, '白栅栏围住小小的草坪，脚边开满雏菊。'),
    ShopItem('concert', '星灯舞台', 'background', 80, '蓝粉色的聚光灯，为桌面留出一方舞台。'),
    ShopItem('studio', '唱片角落', 'background', 65, '木地台、唱片架和音箱，刚好容下一间排练室。'),
    ShopItem('cloudsky', '云端练歌台', 'background', 120, '云朵飘过露台，一架纸飞机时不时掠过天际。', animated=True),
    ShopItem('fireflies', '荷塘萤夜', 'background', 150, '池畔的萤火忽明忽暗，水面漾开一圈圈波纹。', animated=True),
    ShopItem('encore', '糖星彩排夜', 'background', 180, '粉蓝追光在舞台上交错，音符顺着灯束升起。', animated=True),
    ShopItem('musicbox-town', '云上八音街', 'background', 360,
             '跟着天依逛过唱片铺、小桥和摩天轮。她走到哪里，哪里的街景就在柔边圆窗里浮现。', panoramic=True),
)}

FOOD_BY_NAME = {item.name: item for item in ITEMS.values() if item.category == 'food'}
FOODS = {name: (item.price, item.fullness, item.mood, item.xp) for name, item in FOOD_BY_NAME.items()}
QUICK_FOODS = ('小包子', '小笼包', '桂花糕')
AUTO_MEAL = min(FOOD_BY_NAME.values(), key=lambda item: (item.price, -item.fullness))
AUTO_FULLNESS = 10
DEFAULT_BACKGROUND = 'picnic'
