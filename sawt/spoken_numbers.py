"""Exact integer-to-words rendering for spoken riyal amounts."""
UNITS=('صفر','واحد','اثنين','ثلاثة','أربعة','خمسة','ستة','سبعة','ثمانية','تسعة')
TEENS={10:'عشرة',11:'أحد عشر',12:'اثنا عشر'}
TENS={20:'عشرين',30:'ثلاثين',40:'أربعين',50:'خمسين',60:'ستين',70:'سبعين',80:'ثمانين',90:'تسعين'}
HUNDREDS={1:'مئة',2:'مئتين',3:'ثلاثمئة',4:'أربعمئة',5:'خمسمئة',6:'ستمئة',7:'سبعمئة',8:'ثمانمئة',9:'تسعمئة'}


def integer_words(number):
    if type(number) is not int or number<0:raise ValueError('Expected nonnegative integer')
    if number<10:return UNITS[number]
    if number<20:return TEENS.get(number,UNITS[number%10]+' عشر')
    if number<100:
        tens,unit=divmod(number,10)
        return (UNITS[unit]+' و' if unit else '')+TENS[tens*10]
    if number<1000:
        hundreds,remainder=divmod(number,100)
        return HUNDREDS[hundreds]+(' و'+integer_words(remainder) if remainder else '')
    for scale,singular,dual,plural in ((10**9,'مليار','مليارين','مليارات'),(10**6,'مليون','مليونين','ملايين'),(1000,'ألف','ألفين','آلاف')):
        if number>=scale:
            count,remainder=divmod(number,scale)
            prefix=singular if count==1 else dual if count==2 else integer_words(count)+' '+(plural if count<11 else singular)
            return prefix+(' و'+integer_words(remainder) if remainder else '')
